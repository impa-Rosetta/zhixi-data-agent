from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.main import app
from apps.api.rate_limit import get_login_rate_limiter
from packages.platform_core.database import Base, get_db


class AllowRateLimiter:
    def check(self, _: str) -> None:
        return None


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    def override_db() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_login_rate_limiter] = lambda: AllowRateLimiter()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _session(client: TestClient) -> tuple[dict[str, str], str]:
    tokens = client.post(
        "/api/v1/auth/bootstrap",
        json={
            "email": "owner@example.com",
            "display_name": "Owner",
            "password": "correct-horse-battery-staple",
            "workspace_name": "Factory",
            "workspace_slug": "factory",
        },
    ).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    workspace_id = client.get("/api/v1/workspaces", headers=headers).json()[0]["id"]
    return headers, workspace_id


def test_create_run_is_idempotent_and_records_initial_event(client: TestClient) -> None:
    headers, workspace_id = _session(client)
    headers["Idempotency-Key"] = "question-001"
    payload = {"message": "比较本月与上月不良率", "max_model_calls": 4}
    first = client.post(
        f"/api/v1/workspaces/{workspace_id}/analysis-runs", headers=headers, json=payload
    )
    second = client.post(
        f"/api/v1/workspaces/{workspace_id}/analysis-runs", headers=headers, json=payload
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    run_id = first.json()["id"]
    detail = client.get(
        f"/api/v1/workspaces/{workspace_id}/analysis-runs/{run_id}", headers=headers
    )
    assert detail.status_code == 200
    assert detail.json()["status"] == "queued"
    events = client.get(
        f"/api/v1/workspaces/{workspace_id}/analysis-runs/{run_id}/events", headers=headers
    ).json()
    assert events[0]["sequence"] == 1
    assert events[0]["event_type"] == "run.created"


def test_cancel_is_idempotent_and_terminal(client: TestClient) -> None:
    headers, workspace_id = _session(client)
    headers["Idempotency-Key"] = "question-002"
    run = client.post(
        f"/api/v1/workspaces/{workspace_id}/analysis-runs",
        headers=headers,
        json={"message": "分析不良率"},
    ).json()
    endpoint = f"/api/v1/workspaces/{workspace_id}/analysis-runs/{run['id']}/cancel"
    first = client.post(endpoint, headers=headers)
    second = client.post(endpoint, headers=headers)
    assert first.status_code == second.status_code == 200
    assert second.json()["status"] == "cancelled"


def test_list_runs_is_paginated_and_workspace_scoped(client: TestClient) -> None:
    headers, workspace_id = _session(client)
    created_ids: list[str] = []
    for index in range(2):
        request_headers = {**headers, "Idempotency-Key": f"list-{index}"}
        response = client.post(
            f"/api/v1/workspaces/{workspace_id}/analysis-runs",
            headers=request_headers,
            json={"message": f"分析第 {index + 1} 个质量问题"},
        )
        assert response.status_code == 201
        created_ids.append(response.json()["id"])

    page = client.get(
        f"/api/v1/workspaces/{workspace_id}/analysis-runs?limit=1&offset=0",
        headers=headers,
    )

    assert page.status_code == 200
    body = page.json()
    assert body["total"] == 2
    assert body["limit"] == 1
    assert body["offset"] == 0
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] in created_ids
    assert body["items"][0]["goal"].startswith("分析第")
    assert "context" not in body["items"][0]
    assert "idempotency_key" not in body["items"][0]


def test_run_view_restores_messages_without_sensitive_internal_state(
    client: TestClient,
) -> None:
    headers, workspace_id = _session(client)
    request_headers = {**headers, "Idempotency-Key": "view-001"}
    created = client.post(
        f"/api/v1/workspaces/{workspace_id}/analysis-runs",
        headers=request_headers,
        json={"message": "比较本月与上月不良率"},
    ).json()

    response = client.get(
        f"/api/v1/workspaces/{workspace_id}/analysis-runs/{created['id']}/view",
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run"]["id"] == created["id"]
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][0]["content"] == "比较本月与上月不良率"
    assert body["plan"] is None
    assert body["steps"] == []
    assert body["tool_calls"] == []
    assert body["artifacts"] == []
    assert body["evidence"] == []
    assert body["validations"] == []
    assert body["last_event_sequence"] == 1
    serialized = response.text
    assert "idempotency_key" not in serialized
    assert "restricted_reasoning" not in serialized
    assert "next_event_sequence" not in serialized


def test_run_view_does_not_cross_workspace_boundary(client: TestClient) -> None:
    headers, workspace_id = _session(client)
    headers["Idempotency-Key"] = "workspace-boundary"
    run = client.post(
        f"/api/v1/workspaces/{workspace_id}/analysis-runs",
        headers=headers,
        json={"message": "验证工作空间边界"},
    ).json()
    other_workspace_id = "00000000-0000-0000-0000-000000000001"
    response = client.get(
        f"/api/v1/workspaces/{other_workspace_id}/analysis-runs/{run['id']}/view",
        headers=headers,
    )

    assert response.status_code == 403
