import pytest
from fastapi.testclient import TestClient
from nguit_tools import health
from relocation_api.main import app as api_app
from relocation_worker.main import app as worker_app
from voice_gateway.main import app as gateway_app

SERVICES = [("api", api_app), ("voice-gateway", gateway_app), ("worker", worker_app)]


@pytest.mark.parametrize(("name", "app"), SERVICES)
def test_health_ok(name, app):
    res = TestClient(app).get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "service": name}


@pytest.mark.parametrize(("name", "app"), SERVICES)
def test_ready_without_database(name, app, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    res = TestClient(app).get("/health/ready")
    assert res.status_code == 200
    assert res.json()["database"] == "not_configured"


def test_ready_503_when_database_down(monkeypatch):
    monkeypatch.setattr(health, "database_status", lambda: "down")
    res = TestClient(api_app).get("/health/ready")
    assert res.status_code == 503
    assert res.json()["status"] == "not_ready"


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, False), ("false", False), ("", False), ("yes", False), ("true", True), ("TRUE", True)],
)
def test_calling_enabled_defaults_off(value, expected, monkeypatch):
    if value is None:
        monkeypatch.delenv("CALLING_ENABLED", raising=False)
    else:
        monkeypatch.setenv("CALLING_ENABLED", value)
    assert health.calling_enabled() is expected
