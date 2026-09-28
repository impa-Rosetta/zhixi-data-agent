"""HTTP boundary regression using real persistence, without workers or model calls."""

import uuid
from collections.abc import AsyncIterator, Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.main import app
from apps.api.rate_limit import get_login_rate_limiter
from apps.api.routes import analysis_conversations as conversation_routes
from packages.agent_core.persistence import (
    AnalysisConversation,
    AnalysisConversationStatus,
    AnalysisEvent,
    AnalysisMessage,
    AnalysisRun,
    AnalysisRunStatus,
    AnalysisTurn,
)
from packages.platform_core.database import Base, get_db
from packages.platform_core.models import Membership, OutboxEvent, Workspace, WorkspaceRole


class AllowRateLimiter:
    def check(self, _: str) -> None:
        pass


@pytest.fixture
def context() -> Generator[tuple[TestClient, Session, dict[str, str], str], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    def database() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    original = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_login_rate_limiter] = lambda: AllowRateLimiter()
    try:
        with TestClient(app) as client, Session(engine) as db:
            bootstrap = client.post(
                "/api/v1/auth/bootstrap",
                json={
                    "email": "http-regression@example.invalid",
                    "display_name": "Synthetic Owner",
                    "password": "synthetic-http-regression-only",
                    "workspace_name": "HTTP Regression",
                    "workspace_slug": "http-regression",
                },
            )
            assert bootstrap.status_code == 201
            headers = {"Authorization": f"Bearer {bootstrap.json()['access_token']}"}
            workspace = client.get("/api/v1/workspaces", headers=headers).json()[0]["id"]
            yield client, db, headers, workspace
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original)
        engine.dispose()


def _counts(db: Session) -> tuple[int, ...]:
    return tuple(
        int(db.scalar(select(func.count()).select_from(model)) or 0)
        for model in (
            AnalysisConversation,
            AnalysisTurn,
            AnalysisRun,
            AnalysisMessage,
            AnalysisEvent,
            OutboxEvent,
        )
    )


def _conversation(client: TestClient, headers: dict[str, str], workspace: str) -> dict:
    response = client.post(
        f"/api/v1/workspaces/{workspace}/analysis-conversations",
        headers={**headers, "Idempotency-Key": "initial"},
        json={"message": "最近三个月不良率趋势"},
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.parametrize("role", list(WorkspaceRole))
def test_five_role_http_analysis_permissions(context, role: WorkspaceRole) -> None:
    client, db, headers, workspace = context
    conversation = _conversation(client, headers, workspace)
    membership = db.scalar(select(Membership))
    assert membership is not None
    membership.role = role
    db.commit()
    before = _counts(db)
    base = f"/api/v1/workspaces/{workspace}/analysis-conversations"
    expected = 403 if role is WorkspaceRole.AUDITOR else 200
    assert client.get(base, headers=headers).status_code == expected
    assert client.get(f"{base}/{conversation['id']}/view", headers=headers).status_code == expected
    created = client.post(
        base,
        headers={**headers, "Idempotency-Key": "role-create"},
        json={"message": "你好"},
    )
    assert created.status_code == (403 if expected == 403 else 201)
    if expected == 403:
        run_id = db.scalar(select(AnalysisRun.id))
        run_base = f"/api/v1/workspaces/{workspace}/analysis-runs/{run_id}"
        for suffix, payload in (
            ("/cancel", None),
            ("/retry", None),
            ("/confirm", {"approved": True}),
            ("/messages", {"message": "继续"}),
        ):
            assert (
                client.post(
                    run_base + suffix,
                    headers={**headers, "Idempotency-Key": "denied"},
                    json=payload,
                ).status_code
                == 403
            )
        assert client.get(run_base + "/events", headers=headers).status_code == 403
        assert _counts(db) == before


def test_revoked_membership_denies_existing_token_and_has_no_side_effects(context) -> None:
    client, db, headers, workspace = context
    conversation = _conversation(client, headers, workspace)
    membership = db.scalar(select(Membership))
    assert membership is not None
    db.delete(membership)
    db.commit()
    before = _counts(db)
    endpoint = f"/api/v1/workspaces/{workspace}/analysis-conversations/{conversation['id']}"
    assert client.get(endpoint + "/view", headers=headers).status_code == 403
    assert (
        client.post(
            endpoint + "/messages",
            headers={**headers, "Idempotency-Key": "revoked"},
            json={"message": "按月份展开"},
        ).status_code
        == 403
    )
    assert client.get(endpoint + "/events/stream", headers=headers).status_code == 403
    assert _counts(db) == before


def test_member_of_two_workspaces_cannot_readdress_foreign_resources(context) -> None:
    client, db, headers, workspace = context
    conversation = _conversation(client, headers, workspace)
    owner = db.scalar(select(Membership))
    assert owner is not None
    other = Workspace(name="Other Synthetic", slug="other-synthetic")
    db.add(other)
    db.flush()
    db.add(
        Membership(
            workspace_id=other.id,
            user_id=owner.user_id,
            role=WorkspaceRole.WORKSPACE_ADMIN,
        )
    )
    db.commit()
    before = _counts(db)
    base = f"/api/v1/workspaces/{other.id}/analysis-conversations/{conversation['id']}"
    for suffix in ("", "/view", "/events/stream"):
        response = client.get(base + suffix, headers=headers)
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "analysis_conversation.not_found"
    assert (
        client.post(
            base + "/messages",
            headers={**headers, "Idempotency-Key": "foreign"},
            json={"message": "继续"},
        ).status_code
        == 404
    )
    run_id = db.scalar(select(AnalysisRun.id))
    run_base = f"/api/v1/workspaces/{other.id}/analysis-runs/{run_id}"
    for suffix in ("", "/view", "/events", "/events/stream"):
        assert client.get(run_base + suffix, headers=headers).status_code == 404
    for suffix, payload in (
        ("/cancel", None),
        ("/retry", None),
        ("/confirm", {"approved": True}),
        ("/messages", {"message": "继续"}),
    ):
        assert (
            client.post(
                run_base + suffix,
                headers={**headers, "Idempotency-Key": "foreign"},
                json=payload,
            ).status_code
            == 404
        )
    assert _counts(db) == before


def test_follow_up_is_idempotent_paginated_and_keeps_same_conversation(context) -> None:
    client, db, headers, workspace = context
    conversation = _conversation(client, headers, workspace)
    base = f"/api/v1/workspaces/{workspace}/analysis-conversations/{conversation['id']}"
    request_headers = {**headers, "Idempotency-Key": "monthly"}
    for _ in range(2):
        response = client.post(
            base + "/messages", headers=request_headers, json={"message": "按月份展开"}
        )
        assert response.status_code == 200
        assert response.json()["id"] == conversation["id"]
        assert response.json()["last_turn_sequence"] == 2
    assert _counts(db)[:4] == (1, 2, 2, 2)
    assert _counts(db)[-1] == 1  # Queued follow-up must not dispatch alongside active turn.
    page = client.get(base + "/view?limit=1&offset=0", headers=headers).json()
    previous = client.get(base + "/view?limit=1&offset=1", headers=headers).json()
    assert page["total_turns"] == previous["total_turns"] == 2
    assert page["turns"][0]["turn"]["sequence"] == 2
    assert previous["turns"][0]["turn"]["sequence"] == 1
    assert page["turns"][0]["analysis"]["messages"][0]["content"] == "按月份展开"


@pytest.mark.parametrize(
    "state",
    [
        AnalysisRunStatus.WAITING_FOR_CLARIFICATION,
        AnalysisRunStatus.WAITING_FOR_CONFIRMATION,
        AnalysisRunStatus.FAILED_RETRYABLE,
    ],
)
def test_user_reply_resumes_waiting_turn_without_creating_new_turn(context, state) -> None:
    client, db, headers, workspace = context
    conversation = _conversation(client, headers, workspace)
    run = db.scalar(select(AnalysisRun))
    assert run is not None
    run.status = state
    run.context = {**run.context, "binding": {"stale": True}, "result": {"stale": True}}
    run.error_code = "synthetic.retryable"
    db.commit()
    base = f"/api/v1/workspaces/{workspace}/analysis-conversations/{conversation['id']}"
    request_headers = {**headers, "Idempotency-Key": "clarification"}
    for _ in range(2):
        assert (
            client.post(
                base + "/messages", headers=request_headers, json={"message": "统计最近三个月"}
            ).status_code
            == 200
        )
    db.refresh(run)
    assert _counts(db)[:4] == (1, 1, 1, 2)
    assert _counts(db)[-1] == 2
    assert run.status is AnalysisRunStatus.QUEUED
    assert run.error_code is None
    assert run.current_node == (
        "policy_check" if state is AnalysisRunStatus.WAITING_FOR_CONFIRMATION else "understand"
    )
    assert ("binding" in run.context) == (state is AnalysisRunStatus.WAITING_FOR_CONFIRMATION)
    assert run.context["latest_user_message"] == "统计最近三个月"


def test_archived_and_nonactive_turn_requests_are_conflicts_without_writes(context) -> None:
    client, db, headers, workspace = context
    conversation = _conversation(client, headers, workspace)
    base = f"/api/v1/workspaces/{workspace}/analysis-conversations/{conversation['id']}"
    before = _counts(db)
    response = client.post(base + f"/turns/{uuid.uuid4()}/cancel", headers=headers)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "analysis_conversation.turn_not_active"
    archived = db.get(AnalysisConversation, uuid.UUID(conversation["id"]))
    assert archived is not None
    archived.status = AnalysisConversationStatus.ARCHIVED
    db.commit()
    response = client.post(
        base + "/messages",
        headers={**headers, "Idempotency-Key": "archived"},
        json={"message": "继续"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "analysis_conversation.archived"
    assert _counts(db) == before


@pytest.mark.parametrize(
    "operation,payload,error",
    [
        ("retry", None, "analysis_run.retry_not_allowed"),
        ("confirm", {"approved": True}, "analysis_run.confirmation_not_allowed"),
        ("messages", {"message": "继续"}, "analysis_run.message_not_allowed"),
    ],
)
def test_invalid_run_state_rejects_operation_without_partial_writes(
    context,
    operation,
    payload,
    error,
) -> None:
    client, db, headers, workspace = context
    _conversation(client, headers, workspace)
    run_id = db.scalar(select(AnalysisRun.id))
    before = _counts(db)
    endpoint = f"/api/v1/workspaces/{workspace}/analysis-runs/{run_id}/{operation}"
    response = client.post(
        endpoint, headers={**headers, "Idempotency-Key": "invalid"}, json=payload
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == error
    assert _counts(db) == before


@pytest.mark.parametrize("approved", [True, False])
def test_confirmation_transitions_and_dispatches_only_on_approval(context, approved) -> None:
    client, db, headers, workspace = context
    _conversation(client, headers, workspace)
    run = db.scalar(select(AnalysisRun))
    assert run is not None
    run.status = AnalysisRunStatus.WAITING_FOR_CONFIRMATION
    db.commit()
    endpoint = f"/api/v1/workspaces/{workspace}/analysis-runs/{run.id}/confirm"
    response = client.post(endpoint, headers=headers, json={"approved": approved})
    assert response.status_code == 200
    assert response.json()["status"] == ("queued" if approved else "cancelled")
    db.refresh(run)
    assert run.current_node == ("execute" if approved else "cancelled")
    assert _counts(db)[-1] == (2 if approved else 1)
    after = _counts(db)
    assert client.post(endpoint, headers=headers, json={"approved": approved}).status_code == 409
    assert _counts(db) == after


def test_retry_restores_retryable_run_once(context) -> None:
    client, db, headers, workspace = context
    _conversation(client, headers, workspace)
    run = db.scalar(select(AnalysisRun))
    assert run is not None
    run.status = AnalysisRunStatus.FAILED_RETRYABLE
    run.current_node = "execute"
    run.error_code = "synthetic.network"
    db.commit()
    endpoint = f"/api/v1/workspaces/{workspace}/analysis-runs/{run.id}/retry"
    assert client.post(endpoint, headers=headers).status_code == 200
    db.refresh(run)
    assert run.status is AnalysisRunStatus.QUEUED
    assert run.error_code is None
    assert run.current_node == "execute"
    assert _counts(db)[-1] == 2
    after = _counts(db)
    assert client.post(endpoint, headers=headers).status_code == 409
    assert _counts(db) == after


@pytest.mark.parametrize("cursor", ["not-an-integer", "-1"])
def test_run_stream_invalid_cursor_rejected_without_streaming(context, cursor) -> None:
    client, db, headers, workspace = context
    _conversation(client, headers, workspace)
    run_id = db.scalar(select(AnalysisRun.id))
    endpoint = f"/api/v1/workspaces/{workspace}/analysis-runs/{run_id}/events/stream"
    assert client.get(endpoint, headers={**headers, "Last-Event-ID": cursor}).status_code == 422


def test_conversation_stream_rejects_invalid_cursor_and_uses_larger_resume_cursor(
    context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, db, headers, workspace = context
    conversation = _conversation(client, headers, workspace)
    endpoint = (
        f"/api/v1/workspaces/{workspace}/analysis-conversations/{conversation['id']}/events/stream"
    )
    before = _counts(db)
    invalid = client.get(endpoint, headers={**headers, "Last-Event-ID": "invalid"})
    assert invalid.status_code == 400
    assert invalid.json()["detail"]["code"] == "analysis_conversation.invalid_event_cursor"
    cursors: list[int] = []

    async def finite_stream(_db: Session, **kwargs) -> AsyncIterator[str]:
        cursors.append(kwargs["after"])
        yield ": test-only finite stream\n\n"

    monkeypatch.setattr(conversation_routes, "stream_conversation_events", finite_stream)
    for query, header, expected in ((5, "2", 5), (2, "5", 5), (0, None, 0)):
        request_headers = {**headers}
        if header is not None:
            request_headers["Last-Event-ID"] = header
        response = client.get(endpoint + f"?after={query}", headers=request_headers)
        assert response.status_code == 200
        assert response.headers["x-accel-buffering"] == "no"
        assert response.headers["content-type"].startswith("text/event-stream")
        assert cursors[-1] == expected
    assert _counts(db) == before
