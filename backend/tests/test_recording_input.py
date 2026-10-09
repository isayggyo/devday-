import json
from uuid import UUID, uuid4
import pytest
from sqlalchemy import select, func
from backend import recording_input, questions, final_slides
from backend.models import LectureSession, TranscriptSegment, StudentQuestion
from backend.tests.test_sessions import create


def lecture(identifier='Lecture_01'):
    return {'lecture_id': identifier, 'language': 'ko', 'duration': 3, 'segments': [
        {'id': 0, 'start': 0, 'end': 1, 'text': 'Unit original imported statement.'},
        {'id': 1, 'start': 1.2, 'end': 3, 'text': 'Unit second imported statement.'}]}


def send(client, user, session, value, **kwargs):
    return client.post(f"/sessions/{session['id']}/recording-json", headers={'X-Dev-User-Id': user}, files={'file': ('Lecture_01_transcript.json', json.dumps(value).encode(), 'application/json')}, **kwargs)


@pytest.fixture(autouse=True)
def no_provider_calls(monkeypatch):
    monkeypatch.setattr(recording_input, 'schedule_notes', lambda *args: None)
    monkeypatch.setattr(questions, 'schedule_answer', lambda *args: None)


def test_import_preserves_file_origin_question_snapshot_and_offline_finish(materials, monkeypatch):
    client, factory, user, other, session, store = materials
    raw = json.dumps(lecture()).encode(); path = f"/sessions/{session['id']}"; headers = {'X-Dev-User-Id': user}
    result = send(client, user, session, lecture())
    assert result.status_code == 201
    info = result.json()['input']; assert info['segmentCount'] == 2 and info['origin'] == 'recording_json'
    assert store.get(info['objectRef']) == raw
    assert client.get(path+'/recording-json/original', headers=headers).content == raw
    assert client.get(path+'/recording-json/original', headers={'X-Dev-User-Id': other}).status_code == 404
    rows = client.get(path+'/transcript-segments', headers=headers).json()
    assert [(row['startMs'], row['endMs']) for row in rows] == [(0, 1000), (1200, 3000)]
    assert all(row['origin'] == 'recording_json' for row in rows)
    assert send(client, user, session, lecture()).json()['input']['id'] == info['id']
    question = client.post(path+'/questions', headers=headers, json={'clientQuestionId': str(uuid4()), 'questionText': 'Explain the imported statement'}).json()
    evidence = client.get(path+f"/questions/{question['id']}/evidence", headers=headers).json()['bundle']
    assert all(block['sourceRef']['origin'] == 'recording_json' for block in evidence['contextBlocks'] if block['sourceType'] == 'transcript')
    assert client.post(path+'/recording/start', headers=headers, json={'captureId': str(uuid4())}).status_code == 409
    monkeypatch.setattr(final_slides.pool, 'submit', lambda *args, **kwargs: None)
    assert client.post(path+'/finish', headers=headers).status_code == 202
    with factory() as db:
        row = db.get(LectureSession, UUID(session['id'])); assert row.status == 'processing' and row.started_at is None
        assert db.scalar(select(func.count()).select_from(TranscriptSegment).where(TranscriptSegment.session_id == row.id)) == 2


def test_combined_selection_examples_timeline_and_ownership(materials):
    client, factory, user, other, session, _ = materials; path = f"/sessions/{session['id']}"; headers = {'X-Dev-User-Id': user}
    value = {'lectures': [lecture('Lecture_01'), lecture('Lecture_02')], 'student_events': [{'lecture_id': 'Lecture_01', 'timestamp': 1, 'type': 'text_question', 'actor': 'student', 'text': 'Unit file question example'}]}
    assert send(client, user, session, value).status_code == 400
    assert send(client, other, session, value, data={'lecture_id': 'Lecture_01'}).status_code == 404
    result = send(client, user, session, value, data={'lecture_id': 'Lecture_01'})
    assert result.json()['input']['lectureId'] == 'Lecture_01'
    assert len(result.json()['input']['questionExamples']) == 1
    assert send(client, user, session, value, data={'lecture_id': 'Lecture_02'}).status_code == 409
    timeline = [{'slide': 1, 'title': 'Unit timeline title', 'start': 0, 'end': 3}]
    response = client.post(path+'/recording-json/timeline', headers=headers, files={'file': ('timeline.json', json.dumps(timeline).encode())})
    assert response.status_code == 200 and response.json()['input']['timeline'][0]['endMs'] == 3000
    question = client.post(path+'/questions', headers=headers, json={'clientQuestionId': str(uuid4()), 'questionText': 'Unit user entered question'}).json()
    frozen = client.get(path+f"/questions/{question['id']}/evidence", headers=headers).json()['bundle']['contextBlocks']
    assert frozen[0]['sourceRef']['slideTimeline'][0]['title'] == 'Unit timeline title'
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(StudentQuestion).where(StudentQuestion.session_id == UUID(session['id']))) == 1


@pytest.mark.parametrize('value', [[], {}, {'segments': []}, {'segments': [{'start': -1, 'end': 1, 'text': 'invalid'}]},
    {'segments': [{'start': 0, 'end': 1e300, 'text': 'invalid'}]}, {'segments': [{'start': 0, 'end': 1, 'text': ''}]},
    {'segments': [{'start': 0, 'end': 2, 'text': 'first'}, {'start': 1, 'end': 3, 'text': 'overlap'}]}, {'segments': [{'start': 0, 'end': float('nan'), 'text': 'invalid'}]}])
def test_invalid_import_does_not_create_transcripts(materials, value):
    client, factory, user, _, session, _ = materials
    assert send(client, user, session, value).status_code == 400
    with factory() as db:
        assert not db.get(LectureSession, UUID(session['id'])).recording_input
        assert db.scalar(select(func.count()).select_from(TranscriptSegment).where(TranscriptSegment.session_id == UUID(session['id']))) == 0


def test_storage_failure_keeps_input_uncommitted(materials, monkeypatch):
    client, factory, user, _, session, store = materials
    monkeypatch.setattr(store, 'put', lambda *args: (_ for _ in ()).throw(RuntimeError('unavailable')))
    assert send(client, user, session, lecture()).status_code == 503
    with factory() as db: assert db.get(LectureSession, UUID(session['id'])).recording_input is None
