"""Read existing learning records, scoped to one owner and explicitly linked course."""
from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from .auth import current_user
from .db import database_session
from .models import LectureSession, StudentQuestion, GeneratedAnswer, ContextSnapshot, LiveNote, TranscriptSegment, MaterialPage, MaterialDocument
from .session_manager import owned_session

router = APIRouter(tags=['learning-evidence'])


def lecture_sources(db, session_id):
    sources = []
    lecture = db.get(LectureSession, session_id)
    input_info = lecture.recording_input if lecture else None
    for row in db.scalars(select(TranscriptSegment).where(TranscriptSegment.session_id == session_id).order_by(TranscriptSegment.sequence)):
        sources.append({'sourceType': 'transcript', 'sourceId': str(row.id), 'sessionId': str(session_id), 'revision': row.revision,
            'pageNumber': None, 'text': row.text, 'startMs': row.start_ms, 'endMs': row.end_ms,
            'origin': 'recording_json' if input_info else 'realtime', 'inputFilename': input_info['filename'] if input_info else None})
    for page, doc in db.execute(select(MaterialPage, MaterialDocument).join(MaterialDocument).where(MaterialDocument.session_id == session_id,
            MaterialDocument.processing_status.in_(['ready', 'needs_analysis'])).order_by(MaterialDocument.id, MaterialPage.page_number)):
        if page.text.strip(): sources.append({'sourceType': 'material', 'sourceId': str(page.id), 'sessionId': str(session_id),
            'revision': doc.revision, 'pageNumber': page.page_number, 'documentId': str(doc.id), 'filename': doc.filename, 'text': page.text})
    return sources


def collect_evidence(db, session_id, user):
    current = owned_session(db, session_id, user)
    lectures = [current]
    if current.course_key:
        lectures += list(db.scalars(select(LectureSession).where(LectureSession.user_id == user,
            func.lower(LectureSession.course_key) == current.course_key.lower(), LectureSession.id != current.id,
            LectureSession.created_at < current.created_at, LectureSession.test_run_id.is_(None), LectureSession.status == 'completed')
            .order_by(LectureSession.created_at.desc()).limit(5)))
    items = []; diagnostics = []
    for lecture in lectures:
        query = select(StudentQuestion).where(StudentQuestion.session_id == lecture.id).order_by(StudentQuestion.created_at.desc()).limit(30)
        for question in db.scalars(query):
            snapshot = db.get(ContextSnapshot, question.context_snapshot_id)
            answer = db.scalar(select(GeneratedAnswer).where(GeneratedAnswer.question_id == question.id))
            blocks = [block for block in snapshot.frozen_blocks if block['isPrimaryEvidence']]
            # Store excerpts in this bundle, with original revision/IDs; never infer a student's understanding.
            context = [{**block, 'text': block['text'][:5000]} for block in blocks[:12]]
            if len(blocks) > 12 or any(len(block['text']) > 5000 for block in blocks): diagnostics.append('QUESTION_CONTEXT_TRUNCATED')
            items.append({'evidenceId': str(question.id), 'questionId': str(question.id), 'sessionId': str(lecture.id),
                'lectureTitle': lecture.title, 'isPreviousLecture': lecture.id != current.id, 'questionText': question.question_text,
                'snapshotId': str(snapshot.snapshot_id), 'createdAt': question.created_at.isoformat(),
                'context': context, 'sourceIds': [block['id'] for block in blocks], 'reactions': question.reactions or {},
                'relatedConcepts': [{'label': block['text'].strip().splitlines()[0][:140], 'sourceId': block['id']}
                    for block in blocks if block['sourceType'] == 'material' and block['text'].strip()],
                'answerId': str(answer.id) if answer else None, 'answer': answer.answer if answer else None,
                'groundingStatus': answer.grounding_status if answer else None, 'citations': answer.citations if answer else []})
    notes = [{'noteId': str(note.id), 'summary': note.summary, 'sourceRefs': note.source_refs, 'transcriptSegmentIds': note.transcript_segment_ids}
             for note in db.scalars(select(LiveNote).where(LiveNote.session_id == current.id, LiveNote.revision > 0).order_by(LiveNote.start_ms))]
    return {'sessionId': str(current.id), 'studentId': user, 'courseKey': current.course_key, 'questions': items,
        'liveNotes': notes, 'previousLectureIds': [str(lecture.id) for lecture in lectures[1:]],
        'previousLectures': [{'sessionId': str(lecture.id), 'title': lecture.title,
            'coreConcepts': (lecture.final_result or {}).get('coreConcepts', [])} for lecture in lectures[1:]],
        'diagnostics': sorted(set(diagnostics + ([] if current.course_key else ['NO_COURSE_LINK'])))}


@router.get('/sessions/{session_id}/learning-evidence')
def get_learning_evidence(session_id: UUID, user: str = Depends(current_user), db: Session = Depends(database_session)):
    return collect_evidence(db, session_id, user)
