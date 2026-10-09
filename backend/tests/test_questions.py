"""Mock generation is confined to this test boundary; real E2E is separate."""
from uuid import UUID, uuid4
from sqlalchemy import select
import pytest
from backend import questions
from backend.context import primary_evidence, WindowContextProvider
from backend.models import GeneratedAnswer, StudentQuestion, ContextSnapshot, TranscriptSegment
from backend.tests.test_notes import seed
from backend.tests.test_sessions import create


@pytest.fixture(autouse=True)
def no_live_generation(monkeypatch):
    monkeypatch.setattr(questions, 'schedule_answer', lambda *args: None)


def register(environment, session_id, text='unit question', client_id=None):
    client, _, user, _ = environment
    return client.post(f'/sessions/{session_id}/questions', headers={'X-Dev-User-Id': user},
        json={'clientQuestionId': str(client_id or uuid4()), 'questionText': text, 'selectedPageIds': []})


def mock_answer(model, instructions, data):
    primary = next(block for block in data['context']['contextBlocks'] if block['isPrimaryEvidence'])
    ref = primary['sourceRef']
    return model.model_validate({'answer': 'Unit grounded answer', 'groundingStatus': 'grounded', 'needsVisual': False,
        'citations': [{key: ref[key] for key in ['sourceType', 'sourceId', 'revision', 'pageNumber']} | {'excerpt': primary['text']}]})


def test_registration_snapshot_answer_dedup_and_owner(environment):
    client, factory, user, other = environment
    session_id = seed(environment)['id']; client_id = uuid4()
    response = register(environment, session_id, client_id=client_id); assert response.status_code == 202
    question = response.json(); identifier = UUID(question['id'])
    assert question['snapshot']['transcriptHighWatermark'] == 1
    assert register(environment, session_id, client_id=client_id).json()['id'] == question['id']
    assert register(environment, session_id, 'different', client_id).status_code == 409
    questions.answer_job(identifier, user, factory, mock_answer)
    questions.answer_job(identifier, user, factory, lambda *args: pytest.fail('duplicate generation'))
    answer = client.get('/questions/' + question['id'], headers={'X-Dev-User-Id': user}).json()
    assert answer['status'] == 'ready' and answer['answer']['citations']
    assert client.get('/questions/' + question['id'] + '/evidence', headers={'X-Dev-User-Id': other}).status_code == 404
    evidence = client.get('/questions/' + question['id'] + '/evidence', headers={'X-Dev-User-Id': user}).json()
    assert evidence['bundle']['snapshotId'] == question['contextSnapshotId']


def test_empty_context_and_failed_citations_leave_capture_intact(environment):
    client, factory, user, _ = environment
    session = create(client, user); question = register(environment, session['id']).json()
    questions.answer_job(UUID(question['id']), user, factory, lambda *args: pytest.fail('no source needs no API'))
    answer = client.get('/questions/' + question['id'], headers={'X-Dev-User-Id': user}).json()['answer']
    assert answer['groundingStatus'] == 'insufficient_context' and not answer['citations']
    session_id = seed(environment)['id']; question = register(environment, session_id).json()
    def invalid(*args):
        output = mock_answer(*args); output.citations[0].revision = 99; return output
    questions.answer_job(UUID(question['id']), user, factory, invalid)
    with factory() as db:
        assert db.get(StudentQuestion, UUID(question['id'])).error_code == 'INVALID_CITATION'
        assert len(db.scalars(select(TranscriptSegment).where(TranscriptSegment.session_id == UUID(session_id))).all()) == 2
    questions.answer_job(UUID(question['id']), user, factory, mock_answer)
    assert client.get('/questions/' + question['id'], headers={'X-Dev-User-Id': user}).json()['status'] == 'ready'


def test_provider_boundary_and_future_transcript_exclusion(environment):
    client, factory, user, _ = environment
    session_id = seed(environment)['id']; question = register(environment, session_id).json()
    with factory() as db:
        row = db.scalar(select(TranscriptSegment).where(TranscriptSegment.session_id == UUID(session_id)))
        row.text = 'future mutation not in snapshot'; db.commit()
    class Provider:
        called = False
        def getForQuestion(self, text, snapshot):
            self.called = True; bundle = WindowContextProvider().getForQuestion(text, snapshot)
            assert all('future mutation' not in item['text'] for item in primary_evidence(bundle))
            return bundle
    provider = Provider()
    questions.answer_job(UUID(question['id']), user, factory, mock_answer, provider)
    assert provider.called


def test_simultaneous_duplicate_registration_is_atomic(environment):
    from concurrent.futures import ThreadPoolExecutor
    client, factory, user, _ = environment
    session_id = create(client, user)['id']; client_id = uuid4()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: register(environment, session_id, client_id=client_id), range(2)))
    assert all(result.status_code == 202 for result in results)
    assert results[0].json()['id'] == results[1].json()['id']
    with factory() as db:
        assert len(db.scalars(select(StudentQuestion).where(StudentQuestion.session_id == UUID(session_id))).all()) == 1
        assert len(db.scalars(select(ContextSnapshot).where(ContextSnapshot.session_id == UUID(session_id))).all()) == 1
