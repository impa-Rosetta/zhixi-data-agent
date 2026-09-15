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


def test_conversation_api_creates_views_and_continues_the_same_conversation(
    client: TestClient,
) -> None:
    headers, workspace_id = _session(client)
    base = f"/api/v1/workspaces/{workspace_id}/analysis-conversations"
    created = client.post(
        base,
        headers={**headers, "Idempotency-Key": "conversation-api-create"},
        json={"message": "数据库里有哪些表？"},
    )
    assert created.status_code == 201
    conversation_id = created.json()["id"]
    repeated = client.post(
        base,
        headers={**headers, "Idempotency-Key": "conversation-api-create"},
        json={"message": "数据库里有哪些表？"},
    )
    assert repeated.status_code == 201
    assert repeated.json()["id"] == conversation_id

    message = client.post(
        f"{base}/{conversation_id}/messages",
        headers={**headers, "Idempotency-Key": "conversation-api-follow-up"},
        json={"message": "这些表分别有哪些字段？"},
    )
    assert message.status_code == 200
    assert message.json()["id"] == conversation_id
    view = client.get(f"{base}/{conversation_id}/view", headers=headers)
    assert view.status_code == 200
    body = view.json()
    assert body["total_turns"] == 2
    assert [item["turn"]["sequence"] for item in body["turns"]] == [1, 2]
    assert body["turns"][1]["analysis"]["messages"][0]["content"] == "这些表分别有哪些字段？"
    assert "idempotency_key" not in view.text

    page = client.get(base, headers=headers)
    assert page.status_code == 200
    assert page.json()["total"] == 1


def test_conversation_api_requires_authentication_and_workspace_access(
    client: TestClient,
) -> None:
    headers, workspace_id = _session(client)
    base = f"/api/v1/workspaces/{workspace_id}/analysis-conversations"
    assert client.get(base).status_code == 401
    other_workspace_id = "00000000-0000-0000-0000-000000000001"
    assert (
        client.get(
            f"/api/v1/workspaces/{other_workspace_id}/analysis-conversations",
            headers=headers,
        ).status_code
        == 403
    )
