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
    Base.metadata.drop_all(engine)


def bootstrap(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/bootstrap",
        json={
            "email": "owner@example.com",
            "display_name": "Owner",
            "password": "correct-horse-battery-staple",
            "workspace_name": "Demo Factory",
            "workspace_slug": "demo-factory",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_bootstrap_login_refresh_logout_and_me(client: TestClient) -> None:
    initial_tokens = bootstrap(client)
    assert (
        client.post(
            "/api/v1/auth/bootstrap",
            json={
                "email": "other@example.com",
                "display_name": "Other",
                "password": "correct-horse-battery-staple",
                "workspace_name": "Other",
                "workspace_slug": "other-space",
            },
        ).status_code
        == 409
    )

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "OWNER@example.com", "password": "correct-horse-battery-staple"},
    )
    assert login.status_code == 200
    tokens = login.json()
    me = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["workspaces"][0]["role"] == "system_admin"

    refreshed = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": initial_tokens["refresh_token"]}
    )
    assert refreshed.status_code == 200
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": initial_tokens["refresh_token"]}
        ).status_code
        == 401
    )

    new_refresh = refreshed.json()["refresh_token"]
    assert (
        client.post("/api/v1/auth/logout", json={"refresh_token": new_refresh}).status_code == 204
    )
    assert (
        client.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh}).status_code == 401
    )


def test_invitation_and_role_policy(client: TestClient) -> None:
    owner_tokens = bootstrap(client)
    owner_headers = {"Authorization": f"Bearer {owner_tokens['access_token']}"}
    workspace_id = client.get("/api/v1/workspaces", headers=owner_headers).json()[0]["id"]
    invitation = client.post(
        f"/api/v1/workspaces/{workspace_id}/invitations",
        headers=owner_headers,
        json={"email": "analyst@example.com", "role": "analyst"},
    )
    assert invitation.status_code == 201
    analyst_tokens = client.post(
        "/api/v1/auth/accept-invitation",
        json={
            "invite_token": invitation.json()["invite_token"],
            "display_name": "Analyst",
            "password": "another-secure-password",
        },
    )
    assert analyst_tokens.status_code == 201
    analyst_headers = {"Authorization": f"Bearer {analyst_tokens.json()['access_token']}"}
    assert (
        client.get(
            f"/api/v1/workspaces/{workspace_id}/members", headers=analyst_headers
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/workspaces/{workspace_id}/invitations",
            headers=analyst_headers,
            json={"email": "blocked@example.com", "role": "analyst"},
        ).status_code
        == 403
    )

    members = client.get(f"/api/v1/workspaces/{workspace_id}/members", headers=owner_headers)
    assert members.status_code == 200
    analyst = next(item for item in members.json() if item["email"] == "analyst@example.com")
    updated = client.patch(
        f"/api/v1/workspaces/{workspace_id}/members/{analyst['id']}",
        headers=owner_headers,
        json={"role": "auditor"},
    )
    assert updated.status_code == 200
    assert updated.json()["role"] == "auditor"


def test_workspace_admin_cannot_grant_system_admin(client: TestClient) -> None:
    owner_tokens = bootstrap(client)
    owner_headers = {"Authorization": f"Bearer {owner_tokens['access_token']}"}
    workspace_id = client.get("/api/v1/workspaces", headers=owner_headers).json()[0]["id"]
    invitation = client.post(
        f"/api/v1/workspaces/{workspace_id}/invitations",
        headers=owner_headers,
        json={"email": "admin@example.com", "role": "workspace_admin"},
    ).json()
    admin_tokens = client.post(
        "/api/v1/auth/accept-invitation",
        json={
            "invite_token": invitation["invite_token"],
            "display_name": "Workspace Admin",
            "password": "workspace-admin-password",
        },
    ).json()
    admin_headers = {"Authorization": f"Bearer {admin_tokens['access_token']}"}
    assert (
        client.post(
            f"/api/v1/workspaces/{workspace_id}/invitations",
            headers=admin_headers,
            json={"email": "elevated@example.com", "role": "system_admin"},
        ).status_code
        == 403
    )
