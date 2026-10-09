"""Explicit file input, separate from provider-generated realtime transcripts."""
import hashlib
import json
import math
from pathlib import PurePosixPath
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import current_user
from .db import database_session
from .models import TranscriptSegment, TranscriptionTurn, TranscriptionConnection
from .session_manager import owned_session, SessionView
from .storage import ObjectStore, get_object_store
from .notes import schedule_notes

router = APIRouter(prefix='/sessions/{session_id}/recording-json', tags=['recording-input'])


def invalid(message):
    raise HTTPException(400, {'code': 'INVALID_RECORDING_JSON', 'message': message})


def read_file(file, limit):
    name = PurePosixPath((file.filename or '').replace('\\', '/')).name[:240]
    raw = file.file.read(limit+1)
    if not name.lower().endswith('.json') or not raw or len(raw) > limit:
        invalid('JSON 파일 형식이나 크기를 확인해 주세요. 전사는 최대 2MB, 시간표는 최대 128KB입니다.')
    try:
        value = json.loads(raw.decode('utf-8-sig'), parse_constant=lambda value: invalid('유효하지 않은 숫자입니다.'))
    except (ValueError, UnicodeError, RecursionError):
        invalid('UTF-8 JSON 파일을 읽을 수 없습니다.')
    return name, raw, value


def milliseconds(value):
    if type(value) not in (int, float) or not 0 <= value <= 36000 or not math.isfinite(value):
        invalid('시간은 0~36000초 사이의 숫자여야 합니다.')
    return round(value*1000)


def normalize_lecture(value, lecture_id, filename):
    if not isinstance(value, dict): invalid('전사 JSON은 객체여야 합니다.')
    events = value.get('student_events', [])
    if 'lectures' in value:
        lectures = value['lectures']
        if not isinstance(lectures, list) or not 1 <= len(lectures) <= 30 or any(not isinstance(item, dict) for item in lectures): invalid('합본의 lectures 배열이 올바르지 않습니다.')
        selected = [item for item in lectures if item.get('lecture_id') == lecture_id]
        if not lecture_id and len(lectures) == 1: selected = lectures
        if len(selected) != 1: invalid('합본에서 가져올 강의 ID를 하나 선택해 주세요.')
        value = selected[0]
    identifier = value.get('lecture_id') or lecture_id or PurePosixPath(filename).stem.removesuffix('_transcript')
    if not isinstance(identifier, str) or not 1 <= len(identifier) <= 100: invalid('강의 ID가 올바르지 않습니다.')
    rows = value.get('segments')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 2000: invalid('segments에 전사 구간 1~2000개가 필요합니다.')
    segments = []; previous_end = 0
    for index, row in enumerate(rows):
        if not isinstance(row, dict): invalid('전사 구간 형식이 올바르지 않습니다.')
        start, end = milliseconds(row.get('start')), milliseconds(row.get('end'))
        text = row.get('text')
        if start < previous_end or end <= start or not isinstance(text, str) or not text.strip() or len(text) > 4000:
            invalid('구간의 시간 순서·범위 또는 전사 텍스트를 확인해 주세요.')
        segments.append({'index': index, 'startMs': start, 'endMs': end, 'text': text.strip()}); previous_end = end
    if sum(len(row['text']) for row in segments) > 100000: invalid('데모 전사 입력은 총 10만 자 이하입니다.')
    duration = milliseconds(value.get('duration', previous_end/1000))
    if duration < previous_end: invalid('강의 duration이 마지막 전사 시간보다 짧습니다.')
    if not isinstance(events, list) or len(events) > 500: invalid('student_events 배열이 올바르지 않습니다.')
    questions = []
    for event in events:
        if isinstance(event, dict) and event.get('lecture_id') == identifier and event.get('type') == 'text_question':
            text = event.get('text')
            if not isinstance(text, str) or not 1 <= len(text.strip()) <= 2000: invalid('파일의 질문 텍스트가 올바르지 않습니다.')
            time = milliseconds(event.get('timestamp'))
            if time > duration: invalid('질문 시간이 강의 길이를 초과합니다.')
            questions.append({'timestampMs': time, 'text': text.strip()})
    return identifier, duration, segments, questions


def normalize_timeline(value, duration):
    if not isinstance(value, list) or not 1 <= len(value) <= 200: invalid('슬라이드 시간표는 배열이어야 합니다.')
    rows = []; previous_end = 0; known = set()
    for row in value:
        if not isinstance(row, dict): invalid('슬라이드 시간표 항목이 올바르지 않습니다.')
        slide, title = row.get('slide'), row.get('title')
        start, end = milliseconds(row.get('start')), milliseconds(row.get('end'))
        if type(slide) is not int or not 1 <= slide <= 200 or slide in known or not isinstance(title, str) or not 1 <= len(title.strip()) <= 200 or start < previous_end or end <= start or end > duration:
            invalid('슬라이드 번호·제목·시간 범위를 확인해 주세요.')
        rows.append({'slide': slide, 'title': title.strip(), 'startMs': start, 'endMs': end}); known.add(slide); previous_end = end
    return rows


def import_view(session):
    return {'session': SessionView.model_validate(session).model_dump(by_alias=True, mode='json'), 'input': session.recording_input}


@router.post('', status_code=201)
def import_recording(session_id: UUID, file: UploadFile = File(...), lecture_id: str | None = Form(default=None), timeline: UploadFile | None = File(default=None), user: str = Depends(current_user), db: Session = Depends(database_session), store: ObjectStore = Depends(get_object_store)):
    session = owned_session(db, session_id, user, lock=True)
    if session.status not in {'created', 'preparing'}: raise HTTPException(409, {'code': 'INPUT_CLOSED', 'message': '새 강의 또는 준비 중인 강의에 JSON을 가져와 주세요.'})
    name, raw, value = read_file(file, 2*1024*1024)
    identifier, duration, segments, events = normalize_lecture(value, lecture_id, name)
    digest = hashlib.sha256(raw).hexdigest()
    existing = session.recording_input
    if existing:
        if existing['sha256'] == digest and existing['lectureId'] == identifier: return import_view(session)
        raise HTTPException(409, {'code': 'INPUT_ALREADY_IMPORTED', 'message': '이미 전사를 가져온 강의입니다. 다른 파일은 새 강의에서 가져와 주세요.'})
    if db.scalar(select(TranscriptionTurn.id).where(TranscriptionTurn.session_id == session_id).limit(1)):
        raise HTTPException(409, {'code': 'TRANSCRIPT_ALREADY_EXISTS', 'message': '이미 실시간 전사가 있는 강의에는 파일 전사를 섞을 수 없습니다.'})
    input_id = uuid4(); prefix = f'sessions/{session_id}/inputs/{input_id}'
    metadata = {'id': str(input_id), 'origin': 'recording_json', 'filename': name, 'objectRef': prefix+'/transcript.json', 'sha256': digest,
        'lectureId': identifier, 'durationMs': duration, 'segmentCount': len(segments), 'timeline': [], 'questionExamples': events}
    timeline_raw = None
    if timeline:
        timeline_name, timeline_raw, timeline_value = read_file(timeline, 128*1024)
        metadata |= {'timeline': normalize_timeline(timeline_value, duration), 'timelineFilename': timeline_name, 'timelineObjectRef': prefix+'/timeline.json'}
    try:
        store.put(metadata['objectRef'], raw, 'application/json')
        if timeline_raw: store.put(metadata['timelineObjectRef'], timeline_raw, 'application/json')
    except Exception:
        try: store.delete_prefix(prefix+'/')
        except Exception: pass
        raise HTTPException(503, {'code': 'OBJECT_STORAGE_UNAVAILABLE', 'message': '입력 원본 저장에 실패했습니다. 다시 시도해 주세요.'}) from None
    connection = TranscriptionConnection(session_id=session_id, status='imported_json'); db.add(connection); db.flush()
    turns = []
    for row in segments:
        turn = TranscriptionTurn(id=uuid4(), session_id=session_id, connection_id=connection.id, sequence=row['index'], start_ms=row['startMs'], end_ms=row['endMs'], status='committed')
        turns.append(turn)
    db.add_all(turns); db.flush()
    for row, turn in zip(segments, turns):
        db.add(TranscriptSegment(id=turn.id, session_id=session_id, sequence=row['index'], start_ms=row['startMs'], end_ms=row['endMs'], text=row['text'], revision=1))
    session.recording_input = metadata; session.status = 'preparing'
    if session.title in {'새 강의', '업로드 강의'}: session.title = identifier
    try: db.commit()
    except Exception:
        db.rollback(); store.delete_prefix(prefix+'/'); raise
    schedule_notes(session_id, user, True)
    return import_view(session)


@router.post('/timeline')
def attach_timeline(session_id: UUID, file: UploadFile = File(...), user: str = Depends(current_user), db: Session = Depends(database_session), store: ObjectStore = Depends(get_object_store)):
    session = owned_session(db, session_id, user, lock=True)
    if not session.recording_input or session.status != 'preparing': raise HTTPException(409, {'code': 'INPUT_CLOSED', 'message': '전사 JSON을 가져온 뒤 강의를 종료하기 전에 시간표를 연결해 주세요.'})
    name, raw, value = read_file(file, 128*1024)
    rows = normalize_timeline(value, session.recording_input['durationMs'])
    key = f"sessions/{session_id}/inputs/{session.recording_input['id']}/timeline-{hashlib.sha256(raw).hexdigest()}.json"
    try: store.put(key, raw, 'application/json')
    except Exception: raise HTTPException(503, {'code': 'OBJECT_STORAGE_UNAVAILABLE'}) from None
    session.recording_input = session.recording_input | {'timeline': rows, 'timelineFilename': name, 'timelineObjectRef': key}; db.commit()
    return import_view(session)


@router.get('/original')
def original_input(session_id: UUID, timeline: bool = False, user: str = Depends(current_user), db: Session = Depends(database_session), store: ObjectStore = Depends(get_object_store)):
    session = owned_session(db, session_id, user)
    key = (session.recording_input or {}).get('timelineObjectRef' if timeline else 'objectRef')
    if not key: raise HTTPException(404, {'code': 'INPUT_NOT_FOUND'})
    return Response(store.get(key), media_type='application/json')
