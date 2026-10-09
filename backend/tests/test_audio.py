from concurrent.futures import ThreadPoolExecutor
import hashlib
from uuid import uuid4

import pytest

from backend.config import ROOT
from backend.tests.test_materials import materials


def begin(client, user, session):
    capture = str(uuid4())
    result = client.post(f"/sessions/{session['id']}/recording/start", headers={"X-Dev-User-Id": user}, json={"captureId": capture})
    assert result.status_code == 200 and result.json()["status"] == "recording"
    return capture


def chunk(client, user, session, capture, identifier=None, sequence=0, data=None, start=0, end=2000):
    return client.post(f"/sessions/{session['id']}/audio/chunks", headers={"X-Dev-User-Id": user},
        data={"chunk_id": identifier or str(uuid4()), "capture_id": capture, "sequence": sequence, "start_ms": start, "end_ms": end},
        files={"file": ("lecture.wav", data if data is not None else (ROOT / "e2e/fixtures/lecture.wav").read_bytes(), "audio/wav")})


def test_actual_audio_binary_roundtrip_and_stop_idempotence(materials):
    client, _, user, _, session, _ = materials
    capture = begin(client, user, session)
    response = chunk(client, user, session, capture)
    assert response.status_code == 201
    payload = (ROOT / "e2e/fixtures/lecture.wav").read_bytes()
    assert response.json()["sha256"] == hashlib.sha256(payload).hexdigest()
    headers = {"X-Dev-User-Id": user}
    assert client.get(f"/sessions/{session['id']}/audio/file", headers=headers).content == payload
    for _ in range(2):
        result = client.post(f"/sessions/{session['id']}/recording/stop", headers=headers, json={"captureId": capture})
        assert result.status_code == 200 and result.json()["status"] == "finalizing"
        assert result.json()["endedAt"] >= result.json()["startedAt"]


def test_concurrent_duplicate_retries_commit_only_one_chunk(materials):
    client, _, user, _, session, _ = materials
    capture, identifier = begin(client, user, session), str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: chunk(client, user, session, capture, identifier), range(2)))
    assert [result.status_code for result in results] == [201, 201]
    assert sorted(result.json()["deduplicated"] for result in results) == [False, True]
    status = client.get(f"/sessions/{session['id']}/audio", headers={"X-Dev-User-Id": user}).json()
    assert len(status["chunks"]) == 1
    assert chunk(client, user, session, capture, identifier, data=b"changed").status_code == 409
    assert chunk(client, user, session, capture).status_code == 409


def test_owner_capture_and_missing_chunk_isolation(materials):
    client, _, user, other, session, _ = materials
    capture = begin(client, user, session)
    assert chunk(client, other, session, capture).status_code == 404
    assert chunk(client, user, session, str(uuid4())).status_code == 409
    assert chunk(client, user, session, capture, sequence=1).status_code == 201
    headers = {"X-Dev-User-Id": user}
    assert client.get(f"/sessions/{session['id']}/audio/file", headers=headers).status_code == 409
    assert client.get(f"/sessions/{session['id']}/audio", headers={"X-Dev-User-Id": other}).status_code == 404


def test_storage_outage_does_not_acknowledge_then_retry_succeeds(materials, monkeypatch):
    client, _, user, _, session, store = materials
    capture, identifier = begin(client, user, session), str(uuid4())
    put = store.put
    def unavailable(*args):
        raise ConnectionError("outage")
    monkeypatch.setattr(store, "put", unavailable)
    assert chunk(client, user, session, capture, identifier).status_code == 503
    assert client.get(f"/sessions/{session['id']}/audio", headers={"X-Dev-User-Id": user}).json()["chunks"] == []
    monkeypatch.setattr(store, "put", put)
    assert chunk(client, user, session, capture, identifier).status_code == 201


@pytest.mark.parametrize("data,start,end", [(b"", 0, 2000), (b"not a wave", 0, 2000), (None, 2000, 1000)])
def test_invalid_audio_rejected(materials, data, start, end):
    client, _, user, _, session, _ = materials
    capture = begin(client, user, session)
    assert chunk(client, user, session, capture, data=data, start=start, end=end).status_code == 400
