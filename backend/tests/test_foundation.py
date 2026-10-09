import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import text

from backend.app import app
from backend.config import Settings
from backend.db import get_engine


def test_secrets_are_masked():
    settings = Settings(_env_file=None, database_url=SecretStr("postgresql+psycopg://u:secret@localhost/db"), openai_api_key=SecretStr("test-secret-value"))
    assert "test-secret-value" not in settings.model_dump_json()
    assert "u:secret" not in settings.model_dump_json()


def test_development_auth_is_not_production_auth():
    with pytest.raises(ValidationError, match="not permitted"):
        Settings(_env_file=None, app_env="production", auth_mode="development")


@pytest.mark.integration
def test_actual_postgresql_connection():
    with get_engine().connect() as connection:
        assert connection.scalar(text("SELECT 1")) == 1
        assert int(connection.scalar(text("SHOW server_version_num"))) >= 170000


@pytest.mark.integration
def test_actual_health_api():
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json()["database"] == "ok"
    assert response.headers["X-Request-Id"]


def test_database_outage_is_explicit(monkeypatch):
    def unavailable():
        raise RuntimeError("database disconnected")
    monkeypatch.setattr("backend.app.ping_database", unavailable)
    response = TestClient(app).get("/health")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "DATABASE_UNAVAILABLE"


def test_validation_errors_do_not_echo_request_values():
    response = TestClient(app).post("/api/e2e/sessions", json={"run_id": "", "secret": "do-not-echo"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "VALIDATION_ERROR"
    assert "do-not-echo" not in response.text
