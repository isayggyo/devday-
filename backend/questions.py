"""Independent Q&A jobs consume immutable ContextProvider bundles only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import current_user
from .db import database_session, session_factory
from .models import StudentQuestion, GeneratedAnswer, ContextSnapshot, VisualExplanation
from .session_manager import owned_session
from .context import freeze_context, WindowContextProvider, primary_evidence, snapshot_view
from .generation import StrictModel, Citation, generate, validate_citations, GenerationError

router = APIRouter(tags=['questions'])
pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='question-answer')


class QuestionRequest(StrictModel):
    clientQuestionId: UUID
    questionText: str = Field(min_length=1, max_length=2000)
    selectedPageIds: list[UUID] = Field(default_factory=list, max_length=8)


class AnswerOutput(StrictModel):
    answer: str = Field(min_length=1, max_length=6000)
    citations: list[Citation] = Field(max_length=20)
    groundingStatus: Literal['grounded', 'insufficient_context']
    needsVisual: bool


def question_owned(db, identifier, user, session_id=None, lock=False):
    query = select(StudentQuestion).where(StudentQuestion.id == identifier)
    if lock: query = query.with_for_update()
    row = db.scalar(query)
    if not row or (session_id and row.session_id != session_id): raise HTTPException(404, 'Question not found')
    owned_session(db, row.session_id, user)
    return row


def answer_view(row):
    return {'id': str(row.id), 'questionId': str(row.question_id), 'answer': row.answer, 'citations': row.citations,
            'groundingStatus': row.grounding_status, 'needsVisual': row.needs_visual, 'createdAt': row.created_at.isoformat()}


def question_view(db, row):
    answer = db.scalar(select(GeneratedAnswer).where(GeneratedAnswer.question_id == row.id))
    visual = db.scalar(select(VisualExplanation).where(VisualExplanation.answer_id == answer.id)) if answer else None
    from .visuals import visual_view
    snapshot = db.get(ContextSnapshot, row.context_snapshot_id)
    return {'id': str(row.id), 'sessionId': str(row.session_id), 'clientQuestionId': str(row.client_question_id),
        'questionText': row.question_text, 'contextSnapshotId': str(row.context_snapshot_id), 'createdAt': row.created_at.isoformat(),
        'status': row.status, 'errorCode': row.error_code, 'snapshot': snapshot_view(snapshot),
        'answer': answer_view(answer) if answer else None, 'visual': visual_view(visual) if visual else None}


def answer_job(identifier, user, factory=None, generator=None, provider=None):
    factory = factory or session_factory(); generator = generator or generate; provider = provider or WindowContextProvider()
    claimed = False
    try:
        with factory() as db:
            question = question_owned(db, identifier, user, lock=True)
            if question.status == 'ready': return
            if question.status == 'running' and question.updated_at > datetime.now(timezone.utc)-timedelta(seconds=90): return
            snapshot = db.get(ContextSnapshot, question.context_snapshot_id)
            bundle = provider.getForQuestion(question.question_text, snapshot)
            text = question.question_text
            question.status = 'running'; question.error_code = None; question.updated_at = datetime.now(timezone.utc); db.commit(); claimed = True
        evidence = primary_evidence(bundle)
        if not evidence:
            output = AnswerOutput(answer='질문 시점에 확정된 강의 전사나 선택된 자료의 텍스트가 없어 근거가 부족합니다. 전사가 추가된 뒤 새 질문을 등록하거나 자료 페이지를 선택해 주세요.',
                citations=[], groundingStatus='insufficient_context', needsVisual=False)
        else:
            output = generator(AnswerOutput, 'Answer the student question using only the frozen context. Primary evidence supports claims; rolling summaries are secondary and cannot be cited. Distinguish explanations from professor statements. If the specific question cannot be answered from evidence, explicitly mark insufficient_context and explain the gap. Set needsVisual only when a comparison, formula, process or concept diagram would help.',
                {'question': text, 'context': bundle.model_dump()})
        validate_citations(output.citations, evidence)
        if output.groundingStatus == 'grounded' and not output.citations: raise GenerationError('GROUNDED_ANSWER_REQUIRES_CITATIONS')
        with factory() as db:
            question = question_owned(db, identifier, user, lock=True)
            if db.scalar(select(GeneratedAnswer).where(GeneratedAnswer.question_id == identifier)): return
            answer = GeneratedAnswer(question_id=identifier, answer=output.answer, citations=[ref.model_dump() for ref in output.citations],
                grounding_status=output.groundingStatus, needs_visual=output.needsVisual and output.groundingStatus == 'grounded')
            db.add(answer)
            question.status = 'ready'; question.updated_at = datetime.now(timezone.utc); db.commit()
            if answer.needs_visual:
                from .visuals import schedule_visual
                schedule_visual(answer.id, user)
    except Exception as error:
        if claimed:
            with factory() as db:
                question = db.get(StudentQuestion, identifier)
                if question:
                    question.status = 'failed'; question.error_code = str(error) if isinstance(error, GenerationError) else 'ANSWER_GENERATION_FAILED'
                    question.updated_at = datetime.now(timezone.utc); db.commit()


def schedule_answer(identifier, user): pool.submit(answer_job, identifier, user)


@router.post('/sessions/{session_id}/questions', status_code=202)
def register_question(session_id: UUID, request: QuestionRequest, user: str = Depends(current_user), db: Session = Depends(database_session)):
    owned_session(db, session_id, user, lock=True)
    text = request.questionText.strip()
    if not text: raise HTTPException(422, {'code': 'EMPTY_QUESTION'})
    pages = sorted(set(str(identifier) for identifier in request.selectedPageIds))
    existing = db.scalar(select(StudentQuestion).where(StudentQuestion.session_id == session_id, StudentQuestion.client_question_id == request.clientQuestionId))
    if existing:
        if existing.question_text != text or existing.selected_page_ids != pages: raise HTTPException(409, {'code': 'QUESTION_ID_CONFLICT'})
        return question_view(db, existing)
    identifier = uuid4()
    snapshot = freeze_context(db, session_id, user, identifier, [UUID(value) for value in pages])
    row = StudentQuestion(id=identifier, session_id=session_id, client_question_id=request.clientQuestionId, question_text=text,
        selected_page_ids=pages, context_snapshot_id=snapshot.snapshot_id)
    db.add(row); db.commit(); db.refresh(row)
    result = question_view(db, row)
    schedule_answer(row.id, user)
    return result


@router.get('/sessions/{session_id}/questions')
def list_questions(session_id: UUID, user: str = Depends(current_user), db: Session = Depends(database_session)):
    owned_session(db, session_id, user)
    return [question_view(db, row) for row in db.scalars(select(StudentQuestion).where(StudentQuestion.session_id == session_id).order_by(StudentQuestion.created_at)).all()]


@router.get('/questions/{question_id}')
@router.get('/sessions/{session_id}/questions/{question_id}')
def get_question(question_id: UUID, session_id: UUID | None = None, user: str = Depends(current_user), db: Session = Depends(database_session)):
    return question_view(db, question_owned(db, question_id, user, session_id))


@router.get('/questions/{question_id}/evidence')
@router.get('/sessions/{session_id}/questions/{question_id}/evidence')
def get_evidence(question_id: UUID, session_id: UUID | None = None, user: str = Depends(current_user), db: Session = Depends(database_session)):
    row = question_owned(db, question_id, user, session_id)
    snapshot = db.get(ContextSnapshot, row.context_snapshot_id)
    return {'snapshot': snapshot_view(snapshot), 'bundle': WindowContextProvider().getForQuestion(row.question_text, snapshot).model_dump()}


@router.post('/sessions/{session_id}/questions/{question_id}/retry', status_code=202)
def retry_question(session_id: UUID, question_id: UUID, user: str = Depends(current_user), db: Session = Depends(database_session)):
    row = question_owned(db, question_id, user, session_id, lock=True)
    if row.status == 'ready': return question_view(db, row)
    if row.status == 'running' and row.updated_at > datetime.now(timezone.utc)-timedelta(seconds=90): raise HTTPException(409, {'code': 'ANSWER_RUNNING'})
    row.status = 'queued'; row.error_code = None; db.commit(); schedule_answer(row.id, user)
    return question_view(db, row)
