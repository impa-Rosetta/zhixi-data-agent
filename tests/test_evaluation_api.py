import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_evaluation_persistence import _database

from apps.api.dependencies import get_current_user
from apps.api.main import app
from apps.api.routes import evaluations as routes
from packages.evaluation.persistence import EvaluationCaseResult, EvaluationRun
from packages.platform_core.database import get_db
from packages.platform_core.models import Membership, OutboxEvent, User, WorkspaceRole
from packages.platform_core.settings import Settings


@pytest.fixture
def context(monkeypatch):
    db, fixture = _database()
    user = db.get(User, fixture.created_by_user_id)
    membership = Membership(
        user_id=user.id, workspace_id=fixture.workspace_id, role=WorkspaceRole.WORKSPACE_ADMIN
    )
    db.add(membership)
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            evaluation_offline_enabled=True,
        ),
    )
    try:
        with TestClient(app) as client:
            yield client, db, fixture, membership
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_api_create_is_idempotent_and_freezes_draft_identity(context) -> None:
    client, db, fixture, _ = context
    url = f"/api/v1/workspaces/{fixture.workspace_id}/evaluations"
    payload = {"suite_version": "0.1.2", "track": "offline", "max_seconds": 300}
    headers = {"Idempotency-Key": "evaluation-api-create"}
    first = client.post(url, json=payload, headers=headers)
    assert first.status_code == 201
    second = client.post(url, json=payload, headers=headers)
    assert second.json()["id"] == first.json()["id"]
    assert first.json()["calls_used"] == first.json()["tokens_used"] == 0
    assert first.json()["model_version"] == "offline-fixed-v1"
    cases = client.get(f"{url}/{first.json()['id']}/cases")
    assert cases.json()["total"] == 9
    assert "turns" not in cases.text and "password" not in cases.text
    assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 1
    assert db.scalar(select(func.count()).select_from(EvaluationCaseResult)) == 9


def test_latest_draft_is_discoverable_and_creates_all_99_cases(context) -> None:
    client, db, fixture, _ = context
    url = f"/api/v1/workspaces/{fixture.workspace_id}/evaluations"
    suites = client.get(f"{url}/suites")
    assert suites.status_code == 200
    newest = suites.json()["items"][0]
    assert newest["suite_version"] == "0.1.16"
    assert newest["case_count"] == 99
    assert newest["published"] is False
    assert newest["category_counts"] == {
        "standard": 27,
        "multi_turn": 14,
        "ambiguity": 14,
        "anomaly": 24,
        "security": 20,
    }
    created = client.post(
        url,
        json={"suite_version": "0.1.16", "track": "offline", "max_seconds": 300},
        headers={"Idempotency-Key": "evaluation-api-v0116"},
    )
    assert created.status_code == 201
    assert created.json()["suite_digest"] == newest["suite_digest"]
    assert created.json()["calls_used"] == 0
    assert client.get(f"{url}/{created.json()['id']}/cases?limit=50").json()["total"] == 99
    assert db.scalar(select(func.count()).select_from(EvaluationCaseResult)) == 99


@pytest.mark.parametrize(
    "role,read,manage",
    [
        (WorkspaceRole.SYSTEM_ADMIN, 200, 201),
        (WorkspaceRole.WORKSPACE_ADMIN, 200, 201),
        (WorkspaceRole.AUDITOR, 200, 403),
        (WorkspaceRole.DATA_ADMIN, 403, 403),
        (WorkspaceRole.ANALYST, 403, 403),
    ],
)
def test_evaluation_role_matrix(context, role, read, manage) -> None:
    client, db, fixture, membership = context
    membership.role = role
    db.commit()
    url = f"/api/v1/workspaces/{fixture.workspace_id}/evaluations"
    assert client.get(f"{url}/suites").status_code == read
    assert (
        client.post(
            url, json={"suite_version": "0.1.2"}, headers={"Idempotency-Key": "matrix"}
        ).status_code
        == manage
    )


def test_paid_track_and_client_paths_are_rejected(context) -> None:
    client, _, fixture, _ = context
    url = f"/api/v1/workspaces/{fixture.workspace_id}/evaluations"
    headers = {"Idempotency-Key": "invalid"}
    assert (
        client.post(
            url, json={"suite_version": "0.1.2", "track": "live"}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client.post(url, json={"suite_version": "../../secret"}, headers=headers).status_code == 422
    )
    assert (
        client.post(
            url, json={"suite_version": "0.1.2", "provider_key": "fixture"}, headers=headers
        ).status_code
        == 422
    )
    assert client.post(url, json={"suite_version": "9.9.9"}, headers=headers).status_code == 422


def test_cross_workspace_and_revocation_are_denied(context) -> None:
    client, db, fixture, membership = context
    url = f"/api/v1/workspaces/{fixture.workspace_id}/evaluations"
    assert (
        client.get(f"/api/v1/workspaces/{uuid.uuid4()}/evaluations/{fixture.id}").status_code == 403
    )
    db.delete(membership)
    db.commit()
    assert client.get(url).status_code == 403
    assert client.get(f"{url}/{fixture.id}").status_code == 403


def test_disabled_offline_adapter_does_not_enqueue(context, monkeypatch) -> None:
    client, db, fixture, _ = context
    monkeypatch.setattr(routes, "get_settings", lambda: Settings(_env_file=None))
    url = f"/api/v1/workspaces/{fixture.workspace_id}/evaluations"
    result = client.post(
        url, json={"suite_version": "0.1.2"}, headers={"Idempotency-Key": "disabled"}
    )
    assert result.status_code == 503
    assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 0


def test_cancel_is_authorized_and_terminal(context) -> None:
    client, db, fixture, _ = context
    url = f"/api/v1/workspaces/{fixture.workspace_id}/evaluations/{fixture.id}/cancel"
    assert client.post(url).status_code == 204
    assert client.post(url).status_code == 409
    assert db.get(EvaluationRun, fixture.id).status == "cancelled"


def test_server_pagination_and_case_filters_are_workspace_scoped(context) -> None:
    client, db, fixture, _ = context
    url = f"/api/v1/workspaces/{fixture.workspace_id}/evaluations"
    created = client.post(
        url, json={"suite_version": "0.1.2"}, headers={"Idempotency-Key": "paged"}
    )
    assert created.status_code == 201
    first = client.get(f"{url}?limit=1&offset=0").json()
    second = client.get(f"{url}?limit=1&offset=1").json()
    assert first["total"] == second["total"] == 2
    assert first["items"][0]["id"] != second["items"][0]["id"]
    run_id = created.json()["id"]
    security = client.get(f"{url}/{run_id}/cases?category=security&limit=1").json()
    assert security["total"] == 2 and len(security["items"]) == 1
    assert security["items"][0]["category"] == "security"
    filtered = client.get(f"{url}/{run_id}/cases?status=passed").json()
    assert filtered["total"] == 0
    assert client.get(f"{url}/{run_id}/cases?category=../../x").status_code == 422
    assert client.get(f"{url}/{run_id}/cases?status=secret").status_code == 422
    assert db.get(EvaluationRun, uuid.UUID(run_id)) is not None
