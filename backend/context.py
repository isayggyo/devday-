"""Immutable question-time evidence; no semantic search or live-store dependency."""
from datetime import datetime, timezone
from typing import Protocol, Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field
from sqlalchemy import select

from .config import get_settings
from .generation import StrictModel
from .models import ContextSnapshot, TranscriptSegment, LiveNote, MaterialDocument, MaterialPage
from .session_manager import owned_session


class ContextBlock(StrictModel):
    id: str
    sourceType: Literal['transcript', 'material', 'summary']
    text: str
    sourceRef: dict
    isPrimaryEvidence: bool


class ContextBundle(StrictModel):
    snapshotId: str
    contextBlocks: list[ContextBlock]
    coverage: dict
    diagnostics: list[str]


class ContextProvider(Protocol):
    def getForQuestion(self, question, snapshot: ContextSnapshot) -> ContextBundle: ...


class WindowContextProvider:
    def getForQuestion(self, question, snapshot):
        return ContextBundle(snapshotId=str(snapshot.snapshot_id), contextBlocks=snapshot.frozen_blocks,
                             coverage=snapshot.coverage, diagnostics=snapshot.diagnostics)


def freeze_context(db, session_id, user, question_id, selected_page_ids=()):
    # The session row lock serializes question registration against transcript commits
    # and material processing. All evidence text is copied inside this transaction.
    lecture = owned_session(db, session_id, user, lock=True)
    now = datetime.now(timezone.utc)
    transcripts = db.scalars(select(TranscriptSegment).where(TranscriptSegment.session_id == session_id,
        TranscriptSegment.committed_at <= now).order_by(TranscriptSegment.sequence)).all()
    watermark = max((row.sequence for row in transcripts), default=-1)
    end = max((row.end_ms for row in transcripts), default=0)
    window_ms = get_settings().context_window_seconds * 1000
    recent = [row for row in transcripts if row.end_ms > end - window_ms]
    blocks = []
    for row in recent:
        ref = {'sourceType': 'transcript', 'sourceId': str(row.id), 'revision': row.revision, 'pageNumber': None,
               'startMs': row.start_ms, 'endMs': row.end_ms, 'sequence': row.sequence, 'committedAt': row.committed_at.isoformat()}
        if lecture.recording_input:
            ref |= {'origin': 'recording_json', 'inputFilename': lecture.recording_input['filename'], 'lectureId': lecture.recording_input['lectureId'],
                'slideTimeline': [item for item in lecture.recording_input['timeline'] if item['startMs'] < row.end_ms and item['endMs'] > row.start_ms]}
        blocks.append({'id': str(row.id), 'sourceType': 'transcript', 'text': row.text, 'sourceRef': ref, 'isPrimaryEvidence': True})
    revisions = {}; diagnostics = []
    for page_id in dict.fromkeys(selected_page_ids):
        result = db.execute(select(MaterialPage, MaterialDocument).join(MaterialDocument).where(
            MaterialPage.id == page_id, MaterialDocument.session_id == session_id)).first()
        if not result: raise HTTPException(404, {'code': 'MATERIAL_PAGE_NOT_FOUND'})
        page, document = result
        revisions[str(document.id)] = document.revision
        if document.processing_status not in {'ready', 'needs_analysis'}:
            raise HTTPException(409, {'code': 'MATERIAL_NOT_READY'})
        if not page.text.strip(): diagnostics.append('SELECTED_PAGE_HAS_NO_TEXT'); continue
        ref = {'sourceType': 'material', 'sourceId': str(page.id), 'revision': document.revision,
               'pageNumber': page.page_number, 'documentId': str(document.id), 'imageRef': page.image_ref, 'filename': document.filename}
        blocks.append({'id': str(page.id), 'sourceType': 'material', 'text': page.text, 'sourceRef': ref, 'isPrimaryEvidence': True})
    # Summaries are secondary context only; require every underlying transcript
    # to be in this snapshot's primary window, including out-of-order commits.
    included = {str(row.id): row for row in recent}
    note = db.scalar(select(LiveNote).where(LiveNote.session_id == session_id, LiveNote.updated_at <= now,
        LiveNote.revision > 0).order_by(LiveNote.updated_at.desc()).limit(1))
    if note and note.summary and note.transcript_segment_ids and all(identifier in included for identifier in note.transcript_segment_ids):
        blocks.append({'id': str(note.id), 'sourceType': 'summary', 'text': note.summary,
            'sourceRef': {'sourceId': str(note.id), 'revision': note.revision, 'transcriptSegmentIds': note.transcript_segment_ids}, 'isPrimaryEvidence': False})
    primary = [block for block in blocks if block['isPrimaryEvidence']]
    if not primary: diagnostics.append('INSUFFICIENT_CONTEXT')
    if not recent: diagnostics.append('NO_RECENT_CONFIRMED_TRANSCRIPT')
    coverage = {'windowSeconds': get_settings().context_window_seconds, 'startMs': max(0, end-window_ms), 'endMs': end,
                'transcriptCount': len(recent), 'materialPageCount': sum(block['sourceType'] == 'material' for block in blocks),
                'sufficient': bool(primary)}
    snapshot = ContextSnapshot(session_id=session_id, question_id=question_id, transcript_high_watermark=watermark,
        material_revisions=revisions, frozen_blocks=blocks, coverage=coverage, diagnostics=diagnostics, created_at=now)
    db.add(snapshot); db.flush()
    return snapshot


def primary_evidence(bundle):
    return [block.sourceRef | {'text': block.text} for block in bundle.contextBlocks if block.isPrimaryEvidence]


def snapshot_view(row):
    return {'snapshotId': str(row.snapshot_id), 'sessionId': str(row.session_id), 'questionId': str(row.question_id),
        'transcriptHighWatermark': row.transcript_high_watermark, 'materialRevisions': row.material_revisions, 'createdAt': row.created_at.isoformat()}
