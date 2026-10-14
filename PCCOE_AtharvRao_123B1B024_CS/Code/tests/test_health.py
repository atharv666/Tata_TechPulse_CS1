from app.core.config import get_settings
from app.main import create_application
from fastapi.testclient import TestClient


def test_health_endpoint_returns_service_metadata() -> None:
    get_settings.cache_clear()
    with TestClient(create_application()) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "AUTOSAR Architecture Intelligence Assistant"
    assert payload["environment"] == "development"
    assert payload["timestamp"].endswith("Z") or "+00:00" in payload["timestamp"]
