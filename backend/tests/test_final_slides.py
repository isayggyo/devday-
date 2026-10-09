"""Use existing DB fixtures and injected generation; no demo fixtures or E2E harness."""
from uuid import UUID, uuid4
from datetime import timedelta
from sqlalchemy import select
from backend import final_slides, questions
from backend.models import LectureSession, StudentQuestion, ContextSnapshot
from backend.context import freeze_context
from backend.evidence import collect_evidence
from backend.generation import GenerationError
from backend.tests.test_notes import seed


def prepared(environment):
    _, factory, user, _ = environment; session_id = UUID(seed(environment)['id'])
    with factory() as db:
        lecture = db.get(LectureSession, session_id); lecture.status = 'finalizing'; lecture.course_key = 'Unit course'; db.commit()
    return session_id


def generator(model, instructions, data, **kwargs):
    sources = data['sources']; ref = sources[0]
    slide = {'layoutType': 'text_explanation', 'title': 'Unit title', 'body': 'Unit lecture explanation',
        'elements': {'headings': [], 'rows': [], 'nodes': [], 'edges': [], 'equations': [], 'paragraphs': ['Unit explanation']},
        'sourceRefs': [{key: ref[key] for key in ['sourceType', 'sourceId', 'revision', 'pageNumber']} | {'excerpt': ref['text']}],
        'evidenceRefs': [item['evidenceId'] for item in data['EvidenceBundle']['questions'][:1]]}
    if model is final_slides.DeckOutput: return model.model_validate({'coreConcepts': ['Unit core'], 'slides': [slide]})
    return model.model_validate(slide | {'body': 'Apply the unit concept in a new situation', 'hints': ['Unit hint'], 'answer': '4', 'solution': 'Unit concept connection', 'calculationChecks': [{'expression': '2+2', 'expected': '4'}]})


def test_general_deck_and_one_challenge_are_persisted_and_idempotent(environment):
    client, factory, user, other = environment; session_id = prepared(environment); calls = []
    def observed(*args, **kwargs): calls.append(args[0]); return generator(*args, **kwargs)
    final_slides.synthesis_job(session_id, user, factory, observed)
    final_slides.synthesis_job(session_id, user, factory, observed)
    assert calls == [final_slides.DeckOutput, final_slides.ChallengeOutput]
    state = client.get(f'/sessions/{session_id}/slides', headers={'X-Dev-User-Id': user}).json()
    assert state['status'] == 'ready' and state['sessionStatus'] == 'completed'
    assert [slide['kind'] for slide in state['slides']] == ['lecture', 'challenge']
    assert state['slides'][-1]['mathVerification'] == 'verified'
    assert not state['evidenceBundle']['questions']
    assert 'token' not in state and 'sources' not in state
    assert client.get(f'/sessions/{session_id}/slides', headers={'X-Dev-User-Id': other}).status_code == 404


def test_failed_application_keeps_deck_and_retry_adds_only_one_problem(environment):
    client, factory, user, _ = environment; session_id = prepared(environment)
    def failed(model, *args, **kwargs):
        if model is final_slides.ChallengeOutput: raise GenerationError('AI_TIMEOUT')
        return generator(model, *args, **kwargs)
    final_slides.synthesis_job(session_id, user, factory, failed)
    state = client.get(f'/sessions/{session_id}/slides', headers={'X-Dev-User-Id': user}).json()
    assert state['status'] == 'ready' and state['challengeStatus'] == 'failed' and len(state['slides']) == 1
    first_id = state['slides'][0]['id']
    final_slides.synthesis_job(session_id, user, factory, generator, True)
    state = client.get(f'/sessions/{session_id}/slides', headers={'X-Dev-User-Id': user}).json()
    assert state['slides'][0]['id'] == first_id and len(state['slides']) == 2
    final_slides.synthesis_job(session_id, user, factory, generator, True)
    assert len(client.get(f'/sessions/{session_id}/slides', headers={'X-Dev-User-Id': user}).json()['slides']) == 2


def test_same_student_course_history_reactions_and_snapshot_refs(environment, monkeypatch):
    client, factory, user, other = environment; monkeypatch.setattr(questions, 'schedule_answer', lambda *args: None)
    previous = prepared(environment)
    with factory() as db:
        row = db.get(LectureSession, previous); row.status = 'completed'; row.created_at -= timedelta(days=1); db.commit()
    previous_q = client.post(f'/sessions/{previous}/questions', headers={'X-Dev-User-Id': user}, json={'clientQuestionId': str(uuid4()), 'questionText': 'Actual input recorded by unit client'}).json()
    reaction = client.patch(f"/sessions/{previous}/questions/{previous_q['id']}/reaction", headers={'X-Dev-User-Id': user}, json={'reaction': 'more_explanation', 'active': True})
    assert reaction.status_code == 200
    assert client.patch(f"/sessions/{previous}/questions/{previous_q['id']}/reaction", headers={'X-Dev-User-Id': other}, json={'reaction': 'important', 'active': True}).status_code == 404
    current = prepared(environment)
    with factory() as db:
        bundle = collect_evidence(db, current, user)
        assert bundle['previousLectureIds'] == [str(previous)]
        assert bundle['questions'][0]['questionId'] == previous_q['id']
        assert bundle['questions'][0]['reactions']['more_explanation']
        assert bundle['questions'][0]['context'] and bundle['questions'][0]['sourceIds']
        db.get(LectureSession, previous).course_key = 'Other course'; db.commit()
        assert not collect_evidence(db, current, user)['questions']


def test_forged_evidence_and_wrong_calculation_are_rejected(environment):
    _, factory, user, _ = environment; session_id = prepared(environment)
    def forged(model, *args, **kwargs):
        result = generator(model, *args, **kwargs); result.slides[0].evidenceRefs = ['another-student']; return result
    final_slides.synthesis_job(session_id, user, factory, forged)
    with factory() as db: assert db.get(LectureSession, session_id).final_result['errorCode'] == 'INVALID_EVIDENCE_REFERENCE'
    try:
        final_slides.verify_calculations([final_slides.CalculationCheck(expression='2*3', expected='5')]); assert False
    except GenerationError: pass
    assert final_slides.verify_calculations([final_slides.CalculationCheck(expression='det(A)', expected='0')]) == 'not_supported'


def test_finish_progress_has_an_empty_slide_array_before_generation(environment, monkeypatch):
    client, factory, user, _ = environment; session_id = prepared(environment)
    monkeypatch.setattr(final_slides.pool, 'submit', lambda *args, **kwargs: None)
    response = client.post(f'/sessions/{session_id}/finish', headers={'X-Dev-User-Id': user})
    assert response.status_code == 202 and response.json()['status'] == 'queued'
    assert response.json()['slides'] == []
    assert client.get(f'/sessions/{session_id}/synthesis', headers={'X-Dev-User-Id': user}).json()['slides'] == []
