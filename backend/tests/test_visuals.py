"""Schema/storage tests use injected generation; real Responses E2E is separate."""
from uuid import UUID, uuid4
import pytest
from pydantic import ValidationError
from sqlalchemy import select
from backend import questions, visuals
from backend.models import GeneratedAnswer, VisualExplanation
from backend.tests.test_notes import seed
from backend.tests.test_questions import mock_answer


@pytest.fixture(autouse=True)
def no_background_jobs(monkeypatch):
    monkeypatch.setattr(questions, 'schedule_answer', lambda *args: None)
    monkeypatch.setattr(visuals, 'schedule_visual', lambda *args: None)


def prepare(environment):
    client, factory, user, _ = environment; session = seed(environment)
    question = client.post(f"/sessions/{session['id']}/questions", headers={'X-Dev-User-Id': user},
        json={'clientQuestionId': str(uuid4()), 'questionText': 'Unit comparison question'}).json()
    questions.answer_job(UUID(question['id']), user, factory, mock_answer)
    answer = client.get('/questions/' + question['id'], headers={'X-Dev-User-Id': user}).json()['answer']
    return session, question, answer


def output(layout='comparison'):
    elements = {'headings': [], 'rows': [], 'nodes': [], 'edges': [], 'equations': [], 'paragraphs': []}
    if layout == 'comparison': elements.update(headings=['A', 'B'], rows=[{'label': 'Method', 'values': ['A method', 'B method']}])
    elif layout in {'flowchart', 'concept_diagram'}: elements.update(nodes=[{'id': 'a', 'label': 'A', 'detail': ''}, {'id': 'b', 'label': 'B', 'detail': ''}], edges=[{'fromId': 'a', 'toId': 'b', 'label': 'supports'}])
    elif layout == 'equation': elements['equations'] = [{'latex': 'E=mc^2', 'explanation': 'Unit equation fixture, not live evidence'}]
    else: elements['paragraphs'] = ['Unit explanation']
    return {'layoutType': layout, 'title': 'Unit title', 'elements': elements, 'sourceRefs': [{'sourceType': 'transcript', 'sourceId': 'unit-source', 'revision': 1, 'pageNumber': None, 'excerpt': 'unit evidence'}]}


def mock_visual(model, instructions, data):
    result = output(data['preferredLayout'] or 'comparison'); evidence = data['evidence'][0]
    result['sourceRefs'] = [{key: evidence[key] for key in ['sourceType', 'sourceId', 'revision', 'pageNumber']} | {'excerpt': evidence['text']}]
    return model.model_validate(result)


@pytest.mark.parametrize('layout', ['equation', 'comparison', 'flowchart', 'concept_diagram', 'text_explanation'])
def test_layout_schema(layout):
    assert visuals.VisualOutput.model_validate(output(layout)).layoutType == layout
    invalid = output(layout); invalid['unexpectedHtml'] = '<script>bad</script>'
    with pytest.raises(ValidationError): visuals.VisualOutput.model_validate(invalid)


def test_invalid_graph_and_comparison_schema():
    invalid = output('concept_diagram'); invalid['elements']['edges'][0]['toId'] = 'missing'
    with pytest.raises(ValidationError): visuals.VisualOutput.model_validate(invalid)
    invalid = output(); invalid['elements']['rows'][0]['values'] = ['only one']
    with pytest.raises(ValidationError): visuals.VisualOutput.model_validate(invalid)


def test_optional_visual_persistence_sources_dedup_and_owner(environment):
    client, factory, user, other = environment; session, question, answer = prepare(environment)
    with factory() as db: assert not db.scalar(select(VisualExplanation).where(VisualExplanation.answer_id == UUID(answer['id'])))
    endpoint = f"/sessions/{session['id']}/questions/{question['id']}/visual"
    assert client.post(endpoint, headers={'X-Dev-User-Id': other}, json={}).status_code == 404
    assert client.post(endpoint, headers={'X-Dev-User-Id': user}, json={'preferredLayout': 'comparison'}).status_code == 202
    visuals.visual_job(UUID(answer['id']), user, 'comparison', factory, mock_visual)
    visuals.visual_job(UUID(answer['id']), user, 'comparison', factory, lambda *args: pytest.fail('duplicate'))
    result = client.get('/questions/' + question['id'], headers={'X-Dev-User-Id': user}).json()
    assert result['visual']['status'] == 'ready' and result['visual']['revision'] == 1
    assert result['visual']['sourceRefs'][0]['sourceId'] == answer['citations'][0]['sourceId']
    visuals.visual_job(UUID(answer['id']), user, 'concept_diagram', factory, mock_visual)
    result = client.get('/questions/' + question['id'], headers={'X-Dev-User-Id': user}).json()
    assert result['visual']['revision'] == 2 and result['answer']['id'] == answer['id']


def test_invalid_json_or_citation_preserves_answer_and_can_retry(environment):
    client, factory, user, _ = environment; _, question, answer = prepare(environment)
    def invalid(model, instructions, data): return model.model_validate_json('{bad JSON')
    visuals.visual_job(UUID(answer['id']), user, 'comparison', factory, invalid)
    result = client.get('/questions/' + question['id'], headers={'X-Dev-User-Id': user}).json()
    assert result['visual']['status'] == 'failed' and result['answer']['answer'] == answer['answer']
    def invalid_source(*args):
        result = mock_visual(*args); result.sourceRefs[0].sourceId = 'another-session'; return result
    visuals.visual_job(UUID(answer['id']), user, 'comparison', factory, invalid_source)
    result = client.get('/questions/' + question['id'], headers={'X-Dev-User-Id': user}).json()
    assert result['visual']['errorCode'] == 'INVALID_CITATION' and result['answer']['id'] == answer['id']
    visuals.visual_job(UUID(answer['id']), user, 'comparison', factory, mock_visual)
    assert client.get('/questions/' + question['id'], headers={'X-Dev-User-Id': user}).json()['visual']['status'] == 'ready'
