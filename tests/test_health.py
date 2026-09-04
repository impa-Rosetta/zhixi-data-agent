from fastapi.testclient import TestClient

from apps.api.main import app


def test_health_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "api"
    assert payload["version"] == "0.1.0"
    assert payload["timestamp"].endswith("Z")
