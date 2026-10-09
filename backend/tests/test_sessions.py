from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, text
from sqlalchemy.orm import sessionmaker

from backend.app import app
from backend.config import get_settings
from backend.db import database_session
from backend.models import LectureSession
from backend.session_manager import transition


@pytest.fixture
def environment():
    settings = get_settings()
    url = settings.test_database_url.get_secret_value()
    assert url and url != settings.database_url.get_secret_value(), "Use a separate real PostgreSQL test database"
    engine = create_engine(url, pool_pre_ping=True)
    factory = sessionmaker(engine, expire_on_commit=False)
    user = "test-" + uuid4().hex
    other = "test-" + uuid4().hex

    def connection():
        with factory() as db:
            yield db

    app.dependency_overrides[database_session] = connection
    try:
        with TestClient(app) as client:
            yield client, factory, user, other
    finally:
        app.dependency_overrides.pop(database_session, None)
        with factory() as db:
            db.execute(delete(LectureSession).where(LectureSession.user_id.in_([user, other])))
            db.commit()
        engine.dispose()


def create(client, user, title="Linear algebra"):
    result = client.post("/sessions", headers={"X-Dev-User-Id": user}, json={"title": title})
    assert result.status_code == 201
    return result.json()


def test_create_reopen_and_database_persistence(environment):
    client, factory, user, _ = environment
    item = create(client, user)
    assert item["status"] == "created" and item["userId"] == user
    assert item["createdAt"] and item["startedAt"] is None and item["endedAt"] is None
    # A new DB connection/session proves this is not a process-local dictionary.
    with factory() as db:
        assert db.get(LectureSession, UUID(item["id"])).title == "Linear algebra"
    assert client.get("/sessions/" + item["id"], headers={"X-Dev-User-Id": user}).json() == item
    assert len(client.get("/sessions", headers={"X-Dev-User-Id": user}).json()) == 1


def test_owner_isolation_and_invalid_identifiers(environment):
    client, _, user, other = environment
    first, second = create(client, user), create(client, other)
    assert client.get("/sessions/" + first["id"], headers={"X-Dev-User-Id": other}).status_code == 404
    assert [row["id"] for row in client.get("/sessions", headers={"X-Dev-User-Id": other}).json()] == [second["id"]]
    assert client.patch("/sessions/" + first["id"], headers={"X-Dev-User-Id": other}, json={"status": "preparing"}).status_code == 404
    assert client.get("/sessions/not-a-uuid").status_code == 422
    assert client.get("/sessions", headers={"X-Dev-User-Id": "invalid user"}).status_code == 400


def test_state_machine_timestamps_and_invalid_transitions(environment):
    client, factory, user, _ = environment
    item = create(client, user)
    with factory() as db:
        with pytest.raises(HTTPException) as error:
            transition(db, UUID(item["id"]), user, "completed")
        assert error.value.status_code == 409
        db.rollback()
        for status in ["preparing", "recording", "finalizing", "processing", "completed"]:
            row = transition(db, UUID(item["id"]), user, status)
            db.commit()
            assert row.status == status
        assert row.started_at and row.ended_at >= row.started_at
        with pytest.raises(HTTPException):
            transition(db, row.id, user, "recording")


def test_prepare_api_and_client_cannot_fake_completion(environment):
    client, _, user, _ = environment
    item = create(client, user)
    headers = {"X-Dev-User-Id": user}
    assert client.patch("/sessions/" + item["id"], headers=headers, json={"status": "preparing"}).status_code == 200
    assert client.patch("/sessions/" + item["id"], headers=headers, json={"status": "preparing"}).status_code == 409
    assert client.patch("/sessions/" + item["id"], headers=headers, json={"status": "completed"}).status_code == 422
    assert client.post("/sessions", headers=headers, json={"title": "  "}).status_code == 422


def test_deployment_auth_never_uses_dev_identity(environment, monkeypatch):
    client, _, _, _ = environment
    monkeypatch.setattr(get_settings(), "auth_mode", "jwt")
    result = client.get("/sessions", headers={"X-Dev-User-Id": "dev-user"})
    assert result.status_code == 401


def test_versioned_migration_and_status_constraint(environment):
    _, factory, _, _ = environment
    with factory() as db:
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "0003_audio"
        assert db.scalar(text("SELECT count(*) FROM pg_constraint WHERE conname='session_status'")) == 1
