import uuid
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


def test_compile_requires_a_published_semantic_model(client: TestClient) -> None:
    headers, workspace_id = _session(client)
    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/queries/compile",
        headers=headers,
        json={"semantic_model_id": str(uuid.uuid4()), "metrics": ["output"]},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "query.semantic_model_unpublished"


def test_executor_accepts_only_an_existing_validation_id(client: TestClient) -> None:
    headers, workspace_id = _session(client)
    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/queries/{uuid.uuid4()}/execute",
        headers=headers,
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "query.not_found"
