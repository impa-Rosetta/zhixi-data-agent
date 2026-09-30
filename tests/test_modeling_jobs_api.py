from collections.abc import Generator
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import apps.api.routes.modeling_jobs as routes
import apps.api.services.modeling_jobs as service
from apps.api.main import app
from apps.api.rate_limit import get_login_rate_limiter
from packages.modeling.data import ModelDataError, VerifiedTrainingSource
from packages.modeling.synthetic import manufacturing_training_fixture
from packages.platform_core.database import Base, get_db
from tests.test_modeling_host_runtime import ModelStorage
from tests.test_modeling_training import prepared


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
    engine.dispose()


def session(client):
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


def test_modeling_routes_are_disabled_by_default(client):
    headers, workspace_id = session(client)
    response = client.get(
        f"/api/v1/workspaces/{workspace_id}/model-jobs/00000000-0000-0000-0000-000000000001",
        headers=headers,
    )
    assert response.status_code == 503


def test_authorized_http_create_idempotent_detail_and_cancel(client, monkeypatch):
    headers, workspace_id = session(client)
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(modeling_enabled=True))
    store = ModelStorage()
    monkeypatch.setattr(routes, "_storage", lambda: store)
    data = prepared()
    source = VerifiedTrainingSource(
        data.spec.source_artifact_id,
        data.spec.source_snapshot_id,
        data.evidence_id,
        manufacturing_training_fixture(),
        data.spec.source_digest,
    )
    monkeypatch.setattr(service, "load_training_source", lambda *args, **kwargs: source)
    endpoint = f"/api/v1/workspaces/{workspace_id}/model-jobs"
    request_headers = {**headers, "Idempotency-Key": "model-http-1"}
    first = client.post(endpoint, headers=request_headers, json=data.spec.model_dump(mode="json"))
    second = client.post(endpoint, headers=request_headers, json=data.spec.model_dump(mode="json"))
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["status"] == "queued"
    assert len(store.objects) == 1
    detail = client.get(f"{endpoint}/{first.json()['id']}", headers=headers)
    assert detail.status_code == 200 and detail.json()["id"] == first.json()["id"]
    cancelled = client.post(f"{endpoint}/{first.json()['id']}/cancel", headers=headers)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"


def test_revoked_source_returns_safe_error_without_job(client, monkeypatch):
    headers, workspace_id = session(client)
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(modeling_enabled=True))
    store = ModelStorage()
    monkeypatch.setattr(routes, "_storage", lambda: store)
    monkeypatch.setattr(
        service,
        "load_training_source",
        lambda *args, **kwargs: (_ for _ in ()).throw(ModelDataError("policy.denied")),
    )
    data = prepared()
    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/model-jobs",
        headers={**headers, "Idempotency-Key": "model-denied"},
        json=data.spec.model_dump(mode="json"),
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "policy.denied"
    assert store.objects == {}


def test_object_store_outage_is_safe_service_error(client, monkeypatch):
    headers, workspace_id = session(client)
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(modeling_enabled=True))

    def unavailable():
        raise OSError("storage host and secret details must not reach the client")

    monkeypatch.setattr(routes, "_storage", unavailable)
    data = prepared()
    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/model-jobs",
        headers={**headers, "Idempotency-Key": "model-storage-outage"},
        json=data.spec.model_dump(mode="json"),
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "model.service_unavailable"
    assert "secret" not in response.text
