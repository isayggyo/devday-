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
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from backend.config import ROOT
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_current_head()
        assert db.scalar(text("SELECT count(*) FROM pg_constraint WHERE conname='session_status'")) == 1


def test_delete_owned_session_cascades_and_removes_only_its_files(materials, monkeypatch):
    from backend import questions
    from backend.config import ROOT
    from backend.models import MaterialDocument, MaterialPage, StudentQuestion, ContextSnapshot
    from backend.tests.test_materials import upload
    client, factory, user, other, item, store = materials
    monkeypatch.setattr(questions, 'schedule_answer', lambda *args: None)
    doc = upload(client, user, item, (ROOT/'e2e/fixtures/lecture.pdf').read_bytes(), 'lecture.pdf').json()
    headers = {'X-Dev-User-Id': user}; path = '/sessions/'+item['id']
    question = client.post(path+'/questions', headers=headers, json={'clientQuestionId': str(uuid4()), 'questionText': 'Explain retrieval practice', 'selectedPageIds': [doc['pages'][0]['id']]}).json()
    sibling = create(client, user); sibling_key = f"sessions/{sibling['id']}/keep"
    store.put(sibling_key, b'owned sibling content', 'application/octet-stream')
    try:
        assert client.delete(path, headers={'X-Dev-User-Id': other}).status_code == 404
        assert client.get(doc['originalUrl'], headers=headers).status_code == 200
        assert client.delete(path, headers=headers).status_code == 204
        assert client.get(path, headers=headers).status_code == 404
        assert client.delete(path, headers=headers).status_code == 404
        with factory() as db:
            for model, identifier in [(LectureSession, item['id']), (MaterialDocument, doc['id']), (MaterialPage, doc['pages'][0]['id']), (StudentQuestion, question['id']), (ContextSnapshot, question['contextSnapshotId'])]:
                assert db.get(model, UUID(identifier)) is None
        assert not store.client.list_objects_v2(Bucket=store.bucket, Prefix=f"sessions/{item['id']}/").get('Contents')
        assert store.get(sibling_key) == b'owned sibling content'
        assert client.get('/sessions/'+sibling['id'], headers=headers).status_code == 200
    finally:
        store.delete_prefix(f"sessions/{sibling['id']}/")


def test_delete_busy_and_storage_failure_keep_session_for_retry(materials, monkeypatch):
    from backend.models import MaterialDocument
    client, factory, user, _, item, store = materials
    headers = {'X-Dev-User-Id': user}; path = '/sessions/'+item['id']
    with factory() as db:
        for status in ['recording', 'processing']:
            db.get(LectureSession, UUID(item['id'])).status = status; db.commit()
            assert client.delete(path, headers=headers).status_code == 409
        db.get(LectureSession, UUID(item['id'])).status = 'preparing'
        doc = MaterialDocument(session_id=UUID(item['id']), filename='pending.pdf', file_type='pdf', revision=1, original_ref='pending', sha256='0'*64, processing_status='processing')
        db.add(doc); db.commit()
        assert client.delete(path, headers=headers).json()['detail']['code'] == 'MATERIAL_PROCESSING'
        doc.processing_status = 'failed'; db.commit()
    with monkeypatch.context() as patch:
        patch.setattr(store, 'delete_prefix', lambda *args: (_ for _ in ()).throw(RuntimeError('unavailable')))
        assert client.delete(path, headers=headers).status_code == 503
        assert client.get(path, headers=headers).status_code == 200
    assert client.delete(path, headers=headers).status_code == 204


def test_partial_object_deletion_is_reported_as_failure(materials, monkeypatch):
    _, _, _, _, item, store = materials
    prefix = f"sessions/{item['id']}/"; store.put(prefix+'sample', b'test', 'application/octet-stream')
    with monkeypatch.context() as patch:
        patch.setattr(store.client, 'delete_objects', lambda **kwargs: {'Errors': [{'Code': 'AccessDenied'}]})
        with pytest.raises(RuntimeError, match='OBJECT_DELETE_FAILED'):
            store.delete_prefix(prefix)
