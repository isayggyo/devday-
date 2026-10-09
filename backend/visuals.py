"""Optional, independently failing visual explanations of grounded answers."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import current_user
from .db import database_session, session_factory
from .generation import StrictModel, Citation, GenerationError, generate, validate_citations
from .context import WindowContextProvider, primary_evidence
from .models import GeneratedAnswer, StudentQuestion, ContextSnapshot, VisualExplanation
from .questions import question_owned

Layout = Literal['equation', 'comparison', 'flowchart', 'concept_diagram', 'text_explanation']
router = APIRouter(tags=['visuals'])
pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='visual-explanation')


class ComparisonRow(StrictModel):
    label: str = Field(min_length=1, max_length=100)
    values: list[str] = Field(min_length=2, max_length=4)


class Node(StrictModel):
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,30}$')
    label: str = Field(min_length=1, max_length=30)
    detail: str = Field(max_length=70)


class Edge(StrictModel):
    fromId: str
    toId: str
    label: str = Field(max_length=100)


class Equation(StrictModel):
    latex: str = Field(min_length=1, max_length=1500)
    explanation: str = Field(min_length=1, max_length=600)


class Elements(StrictModel):
    headings: list[str] = Field(max_length=4)
    rows: list[ComparisonRow] = Field(max_length=8)
    nodes: list[Node] = Field(max_length=6)
    edges: list[Edge] = Field(max_length=12)
    equations: list[Equation] = Field(max_length=4)
    paragraphs: list[str] = Field(max_length=6)


class VisualOutput(StrictModel):
    layoutType: Layout
    title: str = Field(min_length=1, max_length=140)
    elements: Elements
    sourceRefs: list[Citation] = Field(min_length=1, max_length=20)

    @model_validator(mode='after')
    def layout_content(self):
        content = self.elements
        if self.layoutType == 'comparison':
            if len(content.headings) < 2 or not content.rows or any(len(row.values) != len(content.headings) for row in content.rows):
                raise ValueError('Comparison requires aligned columns')
        elif self.layoutType in {'flowchart', 'concept_diagram'}:
            identifiers = {node.id for node in content.nodes}
            if len(identifiers) < 2 or len(identifiers) != len(content.nodes) or not content.edges:
                raise ValueError('Diagram requires unique connected nodes')
            if any(edge.fromId not in identifiers or edge.toId not in identifiers or edge.fromId == edge.toId for edge in content.edges):
                raise ValueError('Invalid diagram edge')
        elif self.layoutType == 'equation' and not content.equations: raise ValueError('Equation required')
        elif self.layoutType == 'text_explanation' and not content.paragraphs: raise ValueError('Text required')
        return self


class VisualRequest(StrictModel):
    preferredLayout: Layout | None = None


def visual_view(row):
    return {'id': str(row.id), 'answerId': str(row.answer_id), 'layoutType': row.layout_type, 'title': row.title,
            'elements': row.elements, 'sourceRefs': row.source_refs, 'revision': row.revision, 'status': row.status, 'errorCode': row.error_code}


def visual_job(answer_id, user, preferred=None, factory=None, generator=None):
    factory = factory or session_factory(); generator = generator or generate; identifier = None
    try:
        with factory() as db:
            answer = db.scalar(select(GeneratedAnswer).where(GeneratedAnswer.id == answer_id).with_for_update())
            if not answer: return
            question = question_owned(db, answer.question_id, user)
            if answer.grounding_status != 'grounded': return
            row = db.scalar(select(VisualExplanation).where(VisualExplanation.answer_id == answer_id))
            now = datetime.now(timezone.utc)
            if row and row.status == 'running' and row.updated_at > now-timedelta(seconds=90): return
            if row and row.status == 'ready' and (preferred is None or preferred == row.layout_type): return
            if not row: row = VisualExplanation(answer_id=answer_id); db.add(row)
            row.status = 'running'; row.requested_layout = preferred; row.error_code = None; row.updated_at = now; db.commit(); identifier = row.id
            bundle = WindowContextProvider().getForQuestion(question.question_text, db.get(ContextSnapshot, question.context_snapshot_id))
            cited = {ref['sourceId'] for ref in answer.citations}
            evidence = [item for item in primary_evidence(bundle) if item['sourceId'] in cited]
            data = {'question': question.question_text, 'answer': answer.answer, 'evidence': evidence, 'preferredLayout': preferred}
        output = generator(VisualOutput, 'Create one concise visual explanation of this grounded answer. Use the requested layout if provided, otherwise choose the most helpful of equation, comparison, flowchart, concept_diagram or text_explanation. All element fields must be present; use empty arrays for unused fields. Comparison headings contain only the compared items, EXCLUDING the row label column. Every comparison row must contain exactly as many values as headings. Diagrams need unique node IDs and valid edges, labels at most 30 characters and detail at most 70 characters. Use plain labels, no HTML. Formulas must be justified by evidence; never invent a formula. Cite primary evidence. Preserve the limits of the original answer.', data)
        validate_citations(output.sourceRefs, evidence)
        if preferred and output.layoutType != preferred: raise GenerationError('VISUAL_LAYOUT_MISMATCH')
        with factory() as db:
            row = db.get(VisualExplanation, identifier)
            if not row: return
            row.layout_type = output.layoutType; row.title = output.title; row.elements = output.elements.model_dump()
            row.source_refs = [ref.model_dump() for ref in output.sourceRefs]; row.revision += 1; row.status = 'ready'; row.updated_at = datetime.now(timezone.utc); db.commit()
    except Exception as error:
        if identifier:
            with factory() as db:
                row = db.get(VisualExplanation, identifier)
                if row:
                    row.status = 'failed'; row.error_code = str(error) if isinstance(error, GenerationError) else 'VISUAL_INVALID_OR_FAILED'
                    row.updated_at = datetime.now(timezone.utc); db.commit()


def schedule_visual(answer_id, user, preferred=None): pool.submit(visual_job, answer_id, user, preferred)


@router.post('/sessions/{session_id}/questions/{question_id}/visual', status_code=202)
def request_visual(session_id: UUID, question_id: UUID, request: VisualRequest, user: str = Depends(current_user), db: Session = Depends(database_session)):
    question_owned(db, question_id, user, session_id)
    answer = db.scalar(select(GeneratedAnswer).where(GeneratedAnswer.question_id == question_id).with_for_update())
    if not answer: raise HTTPException(409, {'code': 'ANSWER_NOT_READY'})
    if answer.grounding_status != 'grounded': raise HTTPException(409, {'code': 'VISUAL_REQUIRES_GROUNDED_ANSWER'})
    visual = db.scalar(select(VisualExplanation).where(VisualExplanation.answer_id == answer.id))
    if visual and visual.status == 'ready' and (request.preferredLayout is None or request.preferredLayout == visual.layout_type): return visual_view(visual)
    if visual and visual.status == 'running' and visual.updated_at > datetime.now(timezone.utc)-timedelta(seconds=90): return visual_view(visual)
    if not visual: visual = VisualExplanation(answer_id=answer.id); db.add(visual)
    visual.status = 'queued'; visual.requested_layout = request.preferredLayout; visual.error_code = None; db.commit(); db.refresh(visual)
    schedule_visual(answer.id, user, request.preferredLayout)
    return visual_view(visual)
