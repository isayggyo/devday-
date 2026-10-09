from uuid import UUID
from sqlalchemy import select
from backend.models import TranscriptionConnection, TranscriptSegment, LiveNote
from backend.notes import note_job
from backend.transcription import TranscriptAssembler
from backend.tests.test_notes import mock_note
from backend.tests.test_sessions import create


def test_late_lower_sequence_is_merged_and_single_utterance_can_flush(environment):
    client, factory, user, _ = environment
    identifier = UUID(create(client, user)['id'])
    with factory() as db:
        connection = TranscriptionConnection(session_id=identifier); db.add(connection); db.commit(); connection_id = connection.id
    assembler = TranscriptAssembler(factory, identifier, connection_id, user)
    for index in range(3):
        assembler.reserve(index*1000, (index+1)*1000)
        assembler.event({'type': 'input_audio_buffer.committed', 'item_id': str(index)})
    for index in [1, 2]: assembler.event({'type': 'conversation.item.input_audio_transcription.completed', 'item_id': str(index), 'transcript': f'unit evidence {index}'})
    note_job(identifier, user, factory=factory, generator=mock_note)
    assembler.event({'type': 'conversation.item.input_audio_transcription.completed', 'item_id': '0', 'transcript': 'late unit evidence zero'})
    note_job(identifier, user, True, factory, mock_note)
    with factory() as db:
        rows = db.scalars(select(LiveNote).where(LiveNote.session_id == identifier)).all()
        assert len(rows) == 1 and rows[0].revision == 2 and rows[0].start_ms == 0
        assert len(rows[0].transcript_segment_ids) == 3
    second = UUID(create(client, user)['id'])
    with factory() as db:
        connection = TranscriptionConnection(session_id=second); db.add(connection); db.commit(); connection_id = connection.id
    assembler = TranscriptAssembler(factory, second, connection_id, user); assembler.reserve(0, 1000)
    assembler.event({'type': 'input_audio_buffer.committed', 'item_id': 'single'})
    assembler.event({'type': 'conversation.item.input_audio_transcription.completed', 'item_id': 'single', 'transcript': 'one real-shape unit utterance'})
    note_job(second, user, True, factory, mock_note)
    with factory() as db: assert db.scalar(select(LiveNote).where(LiveNote.session_id == second)).revision == 1
