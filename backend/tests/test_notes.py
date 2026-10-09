"""Mock generation boundary tests; live AI validation is separate."""
from uuid import UUID
from sqlalchemy import select
from backend.models import TranscriptionConnection, LiveNote, TranscriptSegment
from backend.transcription import TranscriptAssembler
from backend.notes import note_job, NoteOutput
from backend.generation import GenerationError


def seed(environment):
    client, factory, user, other = environment
    from backend.tests.test_sessions import create
    session = create(client, user); identifier = UUID(session['id'])
    with factory() as db:
        connection = TranscriptionConnection(session_id=identifier); db.add(connection); db.commit(); connection_id = connection.id
    assembler = TranscriptAssembler(factory, identifier, connection_id, user)
    for sequence in range(2):
        assembler.reserve(sequence * 1000, (sequence + 1) * 1000)
        assembler.event({'type': 'input_audio_buffer.committed', 'item_id': str(sequence)})
        assembler.event({'type': 'conversation.item.input_audio_transcription.completed', 'item_id': str(sequence), 'transcript': 'Unit evidence about learning ' + str(sequence)})
    return session


def mock_note(model, instructions, data):
    evidence = data['evidence'][0]
    return model.model_validate({'summary': 'Unit summary from evidence', 'citations': [{key: evidence[key] for key in ['sourceType', 'sourceId', 'revision', 'pageNumber']} | {'excerpt': evidence['text']}]})


def test_batch_persistence_source_links_and_dedup(environment):
    client, factory, user, other = environment; session = seed(environment)
    identifier = UUID(session['id']); calls = []
    def generator(*args): calls.append(True); return mock_note(*args)
    note_job(identifier, user, factory=factory, generator=generator)
    note_job(identifier, user, factory=factory, generator=generator)
    assert len(calls) == 1
    notes = client.get(f"/sessions/{identifier}/notes", headers={'X-Dev-User-Id': user}).json()
    assert len(notes) == 1 and notes[0]['status'] == 'ready' and notes[0]['revision'] == 1
    assert len(notes[0]['transcriptSegmentIds']) == 2
    assert notes[0]['sourceRefs'][0]['sourceId'] in notes[0]['transcriptSegmentIds']
    assert client.get(f"/sessions/{identifier}/notes", headers={'X-Dev-User-Id': other}).status_code == 404


def test_invalid_citation_fails_note_without_mutating_transcripts(environment):
    _, factory, user, _ = environment; session = seed(environment)
    def invalid(model, instructions, data):
        output = mock_note(model, instructions, data); output.citations[0].sourceId = 'wrong-source'; return output
    note_job(UUID(session['id']), user, factory=factory, generator=invalid)
    with factory() as db:
        note = db.scalar(select(LiveNote).where(LiveNote.session_id == UUID(session['id'])))
        assert note.status == 'failed' and note.error_code == 'INVALID_CITATION'
        assert len(db.scalars(select(TranscriptSegment).where(TranscriptSegment.session_id == UUID(session['id']))).all()) == 2
    note_job(UUID(session['id']), user, True, factory, mock_note)
    with factory() as db:
        assert db.scalar(select(LiveNote).where(LiveNote.session_id == UUID(session['id']))).status == 'ready'
