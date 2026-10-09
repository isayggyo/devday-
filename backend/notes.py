from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import threading
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from pydantic import Field

from .auth import current_user
from .config import get_settings
from .db import database_session, session_factory
from .models import LiveNote, TranscriptSegment
from .session_manager import owned_session
from .generation import StrictModel, Citation, generate, validate_citations, GenerationError

router = APIRouter(prefix='/sessions/{session_id}/notes', tags=['notes'])
pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='live-notes')
lock = threading.Lock(); inflight = set(); timers = {}; forced = set()


class NoteOutput(StrictModel):
    summary: str = Field(min_length=1, max_length=1800)
    citations: list[Citation] = Field(min_length=1)


def note_view(row):
    return {'id': str(row.id), 'sessionId': str(row.session_id), 'startMs': row.start_ms, 'endMs': row.end_ms, 'summary': row.summary,
        'transcriptSegmentIds': row.transcript_segment_ids, 'sourceRefs': row.source_refs, 'revision': row.revision, 'status': row.status, 'errorCode': row.error_code}


def note_job(session_id, user, force=False, factory=None, generator=None):
    factory = factory or session_factory(); generator = generator or generate
    identifier = None
    try:
        with factory() as db:
            owned_session(db, session_id, user, lock=True)
            previous = db.scalar(select(LiveNote).where(LiveNote.session_id == session_id).order_by(LiveNote.end_ms.desc(), LiveNote.updated_at.desc()).limit(1))
            if previous and previous.status == 'generating':
                if previous.updated_at > datetime.now(timezone.utc)-timedelta(seconds=90): return
                previous.status = 'failed'; previous.error_code = 'NOTE_WORKER_INTERRUPTED'
            covered = {identifier for note in db.scalars(select(LiveNote).where(LiveNote.session_id == session_id)) for identifier in note.transcript_segment_ids}
            rows = [row for row in db.scalars(select(TranscriptSegment).where(TranscriptSegment.session_id == session_id).order_by(TranscriptSegment.sequence)) if str(row.id) not in covered]
            if not rows: return
            elapsed = (datetime.now(timezone.utc) - previous.updated_at).total_seconds() if previous else 999
            if not force and len(rows) < get_settings().note_min_segments and elapsed < get_settings().note_interval_seconds: return
            if not force and not previous and len(rows) < get_settings().note_min_segments: return
            if previous and (previous.status == 'failed' or (previous.summary and rows[-1].end_ms - previous.start_ms <= 90000)):
                note = previous
                include = set(previous.transcript_segment_ids) | {str(row.id) for row in rows}
                rows = [row for row in db.scalars(select(TranscriptSegment).where(TranscriptSegment.session_id == session_id).order_by(TranscriptSegment.sequence)) if str(row.id) in include]
            else:
                note = LiveNote(session_id=session_id); db.add(note)
            old_summary = note.summary or ''
            note.status = 'generating'; note.updated_at = datetime.now(timezone.utc); db.commit(); identifier = note.id
            evidence = [{'sourceType': 'transcript', 'sourceId': str(row.id), 'revision': row.revision, 'pageNumber': None, 'text': row.text} for row in rows]
            bounds = rows[0].start_ms, rows[-1].end_ms, rows[-1].sequence
        output = generator(NoteOutput, 'Create a concise lecture note from the confirmed transcript batch. Merge improvements with the prior note and avoid repetitive wording. Every note needs primary transcript citations.', {'evidence': evidence, 'previousSummary': old_summary})
        validate_citations(output.citations, evidence)
        with factory() as db:
            note = db.get(LiveNote, identifier)
            if not note: return
            note.summary = output.summary; note.source_refs = [ref.model_dump() for ref in output.citations]; note.transcript_segment_ids = [item['sourceId'] for item in evidence]
            note.start_ms, note.end_ms, note.last_sequence = bounds; note.revision += 1; note.status = 'ready'; note.error_code = None; note.updated_at = datetime.now(timezone.utc); db.commit()
    except Exception as error:
        if identifier:
            with factory() as db:
                note = db.get(LiveNote, identifier)
                if note:
                    note.status = 'failed'; note.error_code = str(error) if isinstance(error, GenerationError) else 'NOTE_GENERATION_FAILED'
                    note.updated_at = datetime.now(timezone.utc); db.commit()


def schedule_notes(session_id, user, force=False):
    with lock:
        if not force and session_id not in timers:
            def flush():
                with lock: timers.pop(session_id, None)
                schedule_notes(session_id, user, True)
            timer = threading.Timer(get_settings().note_interval_seconds, flush); timer.daemon = True
            timers[session_id] = timer; timer.start()
        if session_id in inflight:
            if force: forced.add(session_id)
            return
        inflight.add(session_id)
    def run():
        try: note_job(session_id, user, force)
        finally:
            with lock:
                inflight.discard(session_id); again = session_id in forced; forced.discard(session_id)
            if again: schedule_notes(session_id, user, True)
    pool.submit(run)


@router.get('')
def list_notes(session_id: UUID, user: str = Depends(current_user), db: Session = Depends(database_session)):
    owned_session(db, session_id, user)
    return [note_view(row) for row in db.scalars(select(LiveNote).where(LiveNote.session_id == session_id).order_by(LiveNote.start_ms)).all()]


@router.post('/refresh', status_code=202)
def refresh_notes(session_id: UUID, user: str = Depends(current_user), db: Session = Depends(database_session)):
    owned_session(db, session_id, user); schedule_notes(session_id, user, True)
    return {'status': 'queued'}
