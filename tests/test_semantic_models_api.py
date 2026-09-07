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


def semantic_document() -> dict[str, object]:
    return {
        "entities": [
            {
                "key": "production_order",
                "name": "生产工单",
                "description": "制造执行工单",
                "attributes": [
                    {
                        "key": "order_id",
                        "name": "工单编号",
                        "data_type": "string",
                        "is_identifier": True,
                    },
                    {
                        "key": "planned_quantity",
                        "name": "计划数量",
                        "data_type": "number",
                        "is_identifier": False,
                    },
                ],
            }
        ],
        "relationships": [],
        "dimensions": [
            {
                "key": "order",
                "name": "工单",
                "entity_key": "production_order",
                "attribute_key": "order_id",
                "dimension_type": "categorical",
            }
        ],
        "metrics": [
            {
                "key": "planned_quantity",
                "name": "计划数量",
                "description": "计划生产总量",
                "formula": {"type": "sum", "attribute": "production_order.planned_quantity"},
                "unit": "件",
                "time_grain": None,
                "supported_dimensions": ["order"],
                "aliases": ["计划产量"],
            }
        ],
        "mappings": [],
    }


def test_semantic_model_draft_publish_and_immutability(client: TestClient) -> None:
    headers, workspace_id = bootstrap(client)
    base = f"/api/v1/workspaces/{workspace_id}/semantic-models"
    created = client.post(
        base,
        headers=headers,
        json={"name": "制造质量", "description": "A07 标准语义层"},
    )
    assert created.status_code == 201
    model = created.json()
    assert model["status"] == "draft"
    assert model["version"] == 1

    updated = client.put(
        f"{base}/{model['id']}/draft",
        headers=headers,
        json={"version": 1, **semantic_document()},
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert updated.json()["counts"] == {
        "entities": 1,
        "attributes": 2,
        "relationships": 0,
        "dimensions": 1,
        "metrics": 1,
        "mappings": 0,
    }

    published = client.post(
        f"{base}/{model['id']}/publish",
        headers=headers,
        json={"version": 2},
    )
    assert published.status_code == 200
    assert published.json()["status"] == "published"
    assert published.json()["published_version"] == 1

    rejected = client.put(
        f"{base}/{model['id']}/draft",
        headers=headers,
        json={"version": 2, **semantic_document()},
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "semantic_model.immutable"

    next_draft = client.post(
        f"{base}/{model['id']}/new-draft",
        headers=headers,
        json={"version": published.json()["version"]},
    )
    assert next_draft.status_code == 200
    assert next_draft.json()["status"] == "draft"
    assert next_draft.json()["draft_revision"] == 2
    assert next_draft.json()["published_version"] == 1
    assert next_draft.json()["content_digest"] == published.json()["content_digest"]


def test_semantic_model_workspace_isolation(client: TestClient) -> None:
    headers, workspace_id = bootstrap(client)
    created = client.post(
        f"/api/v1/workspaces/{workspace_id}/semantic-models",
        headers=headers,
        json={"name": "制造质量"},
    ).json()
    foreign = "00000000-0000-0000-0000-000000000001"
    assert (
        client.get(
            f"/api/v1/workspaces/{foreign}/semantic-models/{created['id']}",
            headers=headers,
        ).status_code
        == 403
    )


def test_publish_rejects_invalid_semantic_references(client: TestClient) -> None:
    headers, workspace_id = bootstrap(client)
    base = f"/api/v1/workspaces/{workspace_id}/semantic-models"
    model = client.post(base, headers=headers, json={"name": "Invalid"}).json()
    document = semantic_document()
    metrics = document["metrics"]
    assert isinstance(metrics, list)
    metrics[0]["supported_dimensions"] = ["missing"]
    updated = client.put(
        f"{base}/{model['id']}/draft",
        headers=headers,
        json={"version": 1, **document},
    )
    assert updated.status_code == 422
    assert updated.json()["detail"]["code"] == "semantic_model.invalid_reference"
