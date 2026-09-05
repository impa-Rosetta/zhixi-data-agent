import uuid
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.main import app
from apps.api.rate_limit import get_login_rate_limiter
from packages.platform_core.database import Base, get_db
from packages.platform_core.models import AuditEvent, DataSourceSecret, OutboxEvent


class AllowRateLimiter:
    def check(self, _: str) -> None:
        return None


@pytest.fixture
def api() -> Generator[tuple[TestClient, Engine], None, None]:
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
    with TestClient(app) as client:
        yield client, engine
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def bootstrap(client: TestClient) -> tuple[dict[str, str], str]:
    tokens = client.post(
        "/api/v1/auth/bootstrap",
        json={
            "email": "owner@example.com",
            "display_name": "Owner",
            "password": "correct-horse-battery-staple",
            "workspace_name": "Demo Factory",
            "workspace_slug": "demo-factory",
        },
    ).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    workspace_id = client.get("/api/v1/workspaces", headers=headers).json()[0]["id"]
    return headers, workspace_id


def source_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": "Factory PostgreSQL",
        "description": "Read-only production mirror",
        "source_type": "postgresql",
        "host": "db.example.com",
        "port": 5432,
        "database_name": "factory",
        "tls_mode": "disable",
        "credentials": {"username": "reader", "password": "top-secret-password"},
    }
    payload.update(overrides)
    return payload


def test_data_source_lifecycle_is_versioned_and_never_returns_credentials(
    api: tuple[TestClient, Engine],
) -> None:
    client, engine = api
    headers, workspace_id = bootstrap(client)
    base = f"/api/v1/workspaces/{workspace_id}/data-sources"

    created = client.post(base, headers=headers, json=source_payload())
    assert created.status_code == 201
    body = created.json()
    source = body["data_source"]
    first_job = body["job"]
    assert source["status"] == "testing"
    assert source["version"] == 1
    assert first_job["status"] == "queued"
    assert "top-secret-password" not in created.text
    assert "reader" not in created.text

    listed = client.get(base, headers=headers).json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == source["id"]

    updated = client.patch(
        f"{base}/{source['id']}",
        headers=headers,
        json={"version": 1, "description": "Updated description"},
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert len(client.get(f"{base}/{source['id']}/jobs", headers=headers).json()) == 1

    conflict = client.patch(
        f"{base}/{source['id']}",
        headers=headers,
        json={"version": 1, "name": "Stale update"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "data_source.version_conflict"

    duplicate_job = client.post(
        f"{base}/{source['id']}/test",
        headers={**headers, "Idempotency-Key": "same-request"},
    )
    assert duplicate_job.status_code == 202
    assert duplicate_job.json()["id"] == first_job["id"]

    disabled = client.post(f"{base}/{source['id']}/disable", headers=headers, json={"version": 2})
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"
    assert disabled.json()["version"] == 3

    enabled = client.post(f"{base}/{source['id']}/enable", headers=headers, json={"version": 3})
    assert enabled.status_code == 200
    assert enabled.json()["status"] == "testing"
    assert enabled.json()["version"] == 4

    deleted = client.delete(f"{base}/{source['id']}?version=4", headers=headers)
    assert deleted.status_code == 204
    assert client.get(base, headers=headers).json()["total"] == 0
    assert client.get(f"{base}/{source['id']}", headers=headers).status_code == 404

    with Session(engine) as db:
        secret = db.get(DataSourceSecret, uuid.UUID(source["id"]))
        assert secret is not None
        assert secret.destroyed_at is not None
        assert secret.ciphertext == ""
        outbox = list(db.scalars(select(OutboxEvent)))
        assert outbox
        serialized = repr(outbox[0].payload)
        assert "top-secret-password" not in serialized
        audit_text = " ".join(item.detail or "" for item in db.scalars(select(AuditEvent)))
        assert "top-secret-password" not in audit_text


def test_connector_availability_validation_and_role_policy(
    api: tuple[TestClient, Engine],
) -> None:
    client, _ = api
    headers, workspace_id = bootstrap(client)
    base = f"/api/v1/workspaces/{workspace_id}/data-sources"

    unavailable = client.post(
        base,
        headers=headers,
        json=source_payload(source_type="mysql", port=3306),
    )
    assert unavailable.status_code == 422
    assert unavailable.json()["detail"]["code"] == "connector.not_available"

    invitation = client.post(
        f"/api/v1/workspaces/{workspace_id}/invitations",
        headers=headers,
        json={"email": "analyst@example.com", "role": "analyst"},
    ).json()
    analyst_tokens = client.post(
        "/api/v1/auth/accept-invitation",
        json={
            "invite_token": invitation["invite_token"],
            "display_name": "Analyst",
            "password": "another-secure-password",
        },
    ).json()
    analyst_headers = {"Authorization": f"Bearer {analyst_tokens['access_token']}"}
    assert client.post(base, headers=analyst_headers, json=source_payload()).status_code == 403
