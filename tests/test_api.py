from fastapi.testclient import TestClient

from aiworkmonitor.config import RelaySettings
from aiworkmonitor.relay import create_app


def test_health_is_public_and_devices_are_protected() -> None:
    app = create_app(RelaySettings(token="secret", host="127.0.0.1", port=8765))
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    assert client.get("/api/devices").status_code == 401
    response = client.get("/api/devices", headers={"Authorization": "Bearer secret"})
    assert response.status_code == 200
    assert response.json()["devices"] == []

