"""Demo synthesis reuses Responses, visual JSON and the existing worker pool."""
import ast
from datetime import datetime, timezone, timedelta
from fractions import Fraction
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import current_user
from .db import database_session, session_factory
from .models import LectureSession, AudioChunk, TranscriptionTurn
from .session_manager import owned_session
from .evidence import collect_evidence, lecture_sources
from .generation import StrictModel, GenerationError, generate, validate_citations
from .visuals import VisualOutput, pool

router = APIRouter(prefix='/sessions/{session_id}', tags=['final-slides'])


class SlideOutput(VisualOutput):
    body: str = Field(min_length=1, max_length=2400)
    evidenceRefs: list[str] = Field(max_length=12)


class DeckOutput(StrictModel):
    coreConcepts: list[str] = Field(min_length=1, max_length=12)
    slides: list[SlideOutput] = Field(min_length=1, max_length=6)


class CalculationCheck(StrictModel):
    expression: str = Field(min_length=1, max_length=150)
    expected: str = Field(min_length=1, max_length=80)


class ChallengeOutput(SlideOutput):
    hints: list[str] = Field(min_length=1, max_length=4)
    answer: str = Field(min_length=1, max_length=2000)
    solution: str = Field(min_length=1, max_length=3000)
    calculationChecks: list[CalculationCheck] = Field(max_length=6)


def checked_arithmetic(expression):
    """Small rational arithmetic guard; no eval, symbolic engine or inferred proof."""
    tree = ast.parse(expression, mode='eval')
    if len(list(ast.walk(tree))) > 60: raise ValueError('unsupported')
    def value(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            if len(str(node.value)) > 24: raise ValueError('unsupported')
            return Fraction(str(node.value))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            result = value(node.operand); return -result if isinstance(node.op, ast.USub) else result
        if isinstance(node, ast.BinOp):
            left, right = value(node.left), value(node.right)
            if isinstance(node.op, ast.Add): return left+right
            if isinstance(node.op, ast.Sub): return left-right
            if isinstance(node.op, ast.Mult): return left*right
            if isinstance(node.op, ast.Div): return left/right
            if isinstance(node.op, ast.Pow) and right.denominator == 1 and abs(right) <= 8:
                if max(left.numerator.bit_length(), left.denominator.bit_length())*abs(right) > 4096: raise ValueError('unsupported')
                return left**int(right)
        raise ValueError('unsupported')
    return value(tree.body)


def verify_calculations(checks):
    unsupported = False
    for check in checks:
        try: actual = checked_arithmetic(check.expression); expected = checked_arithmetic(check.expected)
        except (ValueError, SyntaxError, ZeroDivisionError, OverflowError): unsupported = True; continue
        if actual != expected: raise GenerationError('CHALLENGE_CALCULATION_MISMATCH')
    return 'not_supported' if unsupported else 'verified' if checks else 'not_provided'


def prompt_evidence(bundle):
    questions = bundle['questions']
    def priority(item): return (any(item['reactions'].values()), item['createdAt'])
    selected = sorted([item for item in questions if not item['isPreviousLecture']], key=priority, reverse=True)[:10]
    selected += sorted([item for item in questions if item['isPreviousLecture']], key=priority, reverse=True)[:5]
    return {**bundle, 'questions': [{**item, 'answer': (item['answer'] or '')[:2000],
        'context': [{**block, 'text': block['text'][:1200]} for block in item['context'][:2]]} for item in selected], 'liveNotes': bundle['liveNotes'][-8:]}


def validated_slide(output, sources, evidence):
    validate_citations(output.sourceRefs, sources)
    known = {item['evidenceId'] for item in evidence['questions']}
    if any(identifier not in known for identifier in output.evidenceRefs): raise GenerationError('INVALID_EVIDENCE_REFERENCE')
    return output.model_dump() | {'id': str(uuid4()), 'revision': 1, 'status': 'ready', 'errorCode': None}


def source_context(sources, evidence):
    result = list(sources)
    known = {(source['sourceId'], source['revision']) for source in result}
    for item in evidence['questions']:
        for block in item['context']:
            ref = block['sourceRef']
            if (block['id'], ref['revision']) not in known:
                result.append(ref | {'sourceType': block['sourceType'], 'sourceId': block['id'], 'sessionId': item['sessionId'], 'text': block['text']})
                known.add((block['id'], ref['revision']))
    return result


def save_progress(db, session, token, **changes):
    db.refresh(session)
    if not session.final_result or session.final_result.get('token') != token: return False
    session.final_result = session.final_result | changes | {'updatedAt': datetime.now(timezone.utc).isoformat()}
    db.commit(); return True


def synthesis_job(session_id, user, factory=None, generator=None, challenge_only=False):
    factory = factory or session_factory(); generator = generator or generate
    token = None; stage = 'slides'
    try:
        with factory() as db:
            session = owned_session(db, session_id, user, lock=True)
            state = session.final_result or {}
            if state.get('status') in {'generating', 'generating_challenge'} and datetime.fromisoformat(state['updatedAt']) > datetime.now(timezone.utc)-timedelta(seconds=180): return
            if state.get('status') == 'ready' and not challenge_only: return
            if challenge_only and (not state.get('slides') or state.get('challengeStatus') == 'ready'): return
            if challenge_only:
                sources, evidence = state['sources'], state['evidenceBundle']
            else:
                evidence = prompt_evidence(collect_evidence(db, session_id, user))
                sources = source_context(lecture_sources(db, session_id), evidence)
                if not sources: raise GenerationError('NO_LECTURE_EVIDENCE')
                if sum(len(source['text']) for source in sources) > 100000: raise GenerationError('LECTURE_TOO_LONG_FOR_DEMO')
            token = str(uuid4())
            session.final_result = state | {'status': 'generating_challenge' if challenge_only else 'generating', 'token': token,
                'updatedAt': datetime.now(timezone.utc).isoformat(), 'errorCode': None, 'evidenceBundle': evidence, 'sources': sources}
            session.status = 'processing'; db.commit()
            title = session.title
        if not challenge_only:
            deck = generator(DeckOutput,
                'Build a short final lecture slide deck, retaining the CURRENT lecture core and its teaching sequence. Each slide reuses visual elements: unused arrays must be empty. Use text_explanation when a diagram adds no value. Personalize explanation depth/order/visuals for actual student questions and reactions. Explain confusing concepts, connect only relevant previous-course questions, and never infer a learner profile. Primary lecture sources support factual claims; AI answers/notes are secondary context. Personalized slides must include the ORIGINAL question evidenceId in evidenceRefs. With no questions, create a normal lecture deck. Every slide requires exact sourceRefs. At least one slide must cite CURRENT lecture sources. Do not include a practice problem yet.',
                {'lectureTitle': title, 'sessionId': str(session_id), 'sources': sources, 'EvidenceBundle': evidence}, max_output_tokens=7500, timeout=90)
            slides = [validated_slide(slide, sources, evidence) | {'kind': 'lecture'} for slide in deck.slides]
            current_ids = {source['sourceId'] for source in sources if source.get('sessionId') == str(session_id)}
            if not any(ref['sourceId'] in current_ids for slide in slides for ref in slide['sourceRefs']): raise GenerationError('CURRENT_LECTURE_SOURCE_REQUIRED')
            with factory() as db:
                session = owned_session(db, session_id, user)
                if not save_progress(db, session, token, slides=slides, coreConcepts=deck.coreConcepts,
                    status='generating_challenge', challengeStatus='generating', challengeError=None,
                    revision=(session.final_result.get('revision', 0)+1)): return
        stage = 'challenge'
        with factory() as db:
            session = owned_session(db, session_id, user); state = session.final_result
            base_slides = [slide for slide in state['slides'] if slide['kind'] == 'lecture']
            concepts = state['coreConcepts']
        # Exactly one separate Responses call per challenge attempt, after the deck is persisted.
        challenge = generator(ChallengeOutput,
            'Create ONE application challenge in a NEW concrete situation, using the current core concepts and the actual student questions/reactions. Connect previous-course concepts only when relevant; otherwise rely on the current lecture. With no questions create a general application challenge. Avoid repetitive arithmetic drills. body is the QUESTION only: do NOT leak hints or the answer in body/elements/title. hints, answer and solution are separate. The solution must explain concept connections and distinguish the invented problem situation from lecture facts. Use the existing visual elements, or text_explanation paragraphs restating only the question. Exact sourceRefs establish the underlying concepts; evidenceRefs refer to original student question IDs. If simple numeric arithmetic is involved, supply calculationChecks using only numeric +,-,*,/,** and parentheses (no variables/functions); no unsupported claim of verified mathematics.',
            {'lectureTitle': title, 'coreConcepts': concepts, 'EvidenceBundle': evidence,
             'sources': sources, 'finalSlideSummary': [{'title': slide['title'], 'body': slide['body']} for slide in base_slides]}, max_output_tokens=5500, timeout=90)
        slide = validated_slide(challenge, sources, evidence) | {'kind': 'challenge', 'mathVerification': verify_calculations(challenge.calculationChecks)}
        with factory() as db:
            session = owned_session(db, session_id, user)
            if save_progress(db, session, token, slides=base_slides+[slide], status='ready', challengeStatus='ready', challengeError=None):
                session.status = 'completed'; db.commit()
    except Exception as error:
        code = str(error) if isinstance(error, GenerationError) else 'FINAL_GENERATION_FAILED'
        with factory() as db:
            session = db.get(LectureSession, session_id)
            if not session or session.user_id != user: return
            if token and (session.final_result or {}).get('token') not in {None, token}: return
            state = session.final_result or {}
            has_slides = bool(state.get('slides'))
            session.final_result = state | {'status': 'ready' if stage == 'challenge' and has_slides else 'failed',
                'challengeStatus': 'failed' if stage == 'challenge' else state.get('challengeStatus', 'pending'),
                'challengeError': code if stage == 'challenge' else None, 'errorCode': code if stage != 'challenge' else None,
                'updatedAt': datetime.now(timezone.utc).isoformat()}
            session.status = 'completed' if has_slides else 'failed'; db.commit()


def final_view(session):
    state = session.final_result
    if not state: return {'status': 'not_started', 'slides': [], 'sessionId': str(session.id), 'sessionStatus': session.status}
    return {key: value for key, value in state.items() if key not in {'token', 'sources'}} | {'sessionId': str(session.id), 'slides': state.get('slides', []),
        'sessionStatus': session.status, 'sourceIndex': [{key: value for key, value in source.items() if key != 'text'} for source in state.get('sources', [])]}


@router.post('/finish', status_code=202)
def finish(session_id: UUID, user: str = Depends(current_user), db: Session = Depends(database_session)):
    session = owned_session(db, session_id, user, lock=True)
    state = session.final_result or {}
    if state.get('status') in {'ready', 'empty'}: return final_view(session)
    if state.get('status') in {'generating', 'generating_challenge', 'queued'} and datetime.fromisoformat(state['updatedAt']) > datetime.now(timezone.utc)-timedelta(seconds=180): return final_view(session)
    if session.status not in {'finalizing', 'processing', 'failed', 'completed'}: raise HTTPException(409, {'code': 'STOP_RECORDING_FIRST', 'message': '먼저 녹음을 중지해 원본 저장과 전사 확정을 마쳐 주세요.'})
    if db.scalar(select(TranscriptionTurn.id).where(TranscriptionTurn.session_id == session_id, TranscriptionTurn.status == 'pending').limit(1)):
        raise HTTPException(409, {'code': 'TRANSCRIPTION_PENDING', 'message': '마지막 전사가 확정될 때까지 기다려 주세요.'})
    chunks = db.scalars(select(AudioChunk).where(AudioChunk.session_id == session_id).order_by(AudioChunk.sequence)).all()
    if any(row.sequence != index for index, row in enumerate(chunks)): raise HTTPException(409, {'code': 'AUDIO_CHUNKS_MISSING', 'message': '미전송 음성 청크를 재전송한 뒤 다시 종료해 주세요.'})
    if not lecture_sources(db, session_id):
        session.ended_at = session.ended_at or datetime.now(timezone.utc)
        session.status = 'completed'
        session.final_result = {'status': 'empty', 'slides': [], 'updatedAt': datetime.now(timezone.utc).isoformat()}
        db.commit()
        return final_view(session)
    session.ended_at = session.ended_at or datetime.now(timezone.utc)
    session.status = 'processing'
    session.final_result = state | {'status': 'queued', 'updatedAt': datetime.now(timezone.utc).isoformat()}; db.commit()
    pool.submit(synthesis_job, session_id, user)
    return final_view(session)


@router.get('/synthesis')
@router.get('/slides')
def get_final(session_id: UUID, user: str = Depends(current_user), db: Session = Depends(database_session)):
    return final_view(owned_session(db, session_id, user))


@router.post('/challenge/retry', status_code=202)
def retry_challenge(session_id: UUID, user: str = Depends(current_user), db: Session = Depends(database_session)):
    session = owned_session(db, session_id, user, lock=True); state = session.final_result or {}
    if not state.get('slides'): raise HTTPException(409, {'code': 'SLIDES_NOT_READY'})
    if state.get('challengeStatus') == 'ready': return final_view(session)
    if state.get('status') in {'generating', 'generating_challenge'} and datetime.fromisoformat(state['updatedAt']) > datetime.now(timezone.utc)-timedelta(seconds=180): return final_view(session)
    session.final_result = state | {'status': 'queued', 'updatedAt': datetime.now(timezone.utc).isoformat()}; db.commit()
    pool.submit(synthesis_job, session_id, user, challenge_only=True)
    return final_view(session)


@router.get('/slides/pdf')
def export_pdf(session_id: UUID, include_answers: bool = False, user: str = Depends(current_user), db: Session = Depends(database_session)):
    import json
    import subprocess
    from scripts.node_runtime import ROOT, find_node, node_environment
    session = owned_session(db, session_id, user)
    state = session.final_result or {}
    if not state.get('slides'): raise HTTPException(409, {'code': 'SLIDES_NOT_READY'})
    node = find_node()
    try:
        output = subprocess.run([node, '--experimental-strip-types', str(ROOT/'scripts/export_final_pdf.mjs')],
            input=json.dumps({'slides': state['slides'], 'evidenceBundle': state.get('evidenceBundle'), 'includeAnswers': include_answers}, ensure_ascii=False).encode('utf-8'),
            cwd=ROOT, env=node_environment(node), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, check=True,
            creationflags=subprocess.CREATE_NO_WINDOW if __import__('os').name == 'nt' else 0)
        if not output.stdout.startswith(b'%PDF-'): raise RuntimeError('invalid PDF')
    except Exception: raise HTTPException(503, {'code': 'PDF_EXPORT_FAILED', 'message': 'PDF 내보내기에 실패했습니다. 슬라이드는 보존됩니다.'}) from None
    return Response(output.stdout, media_type='application/pdf', headers={'Content-Disposition': f'attachment; filename="lecture-{session_id}.pdf"'})
