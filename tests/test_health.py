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


def test_local_browser_cors_preflight_allows_task_idempotency_header() -> None:
    with TestClient(app) as client:
        response = client.options(
            "/health",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Idempotency-Key",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert "Idempotency-Key" in response.headers["access-control-allow-headers"]
