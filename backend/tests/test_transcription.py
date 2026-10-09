"""Deterministic provider-event unit fixtures; real AI is tested separately in e2e/transcription.mjs."""
from uuid import UUID
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import SecretStr
from sqlalchemy import select, func

from backend.config import get_settings
from backend.models import TranscriptionConnection, TranscriptSegment, TranscriptionTicket
from backend.transcription import TranscriptAssembler, consume_ticket
from backend.tests.test_audio import begin


def test_partial_out_of_order_final_and_duplicate_events(materials):
    client, factory, user, other, session, _ = materials
    identifier = UUID(session['id'])
    with factory() as db:
        connection = TranscriptionConnection(session_id=identifier); db.add(connection); db.commit(); connection_id = connection.id
    assembler = TranscriptAssembler(factory, identifier, connection_id, user)
    assembler.reserve(0, 1000); assembler.reserve(1000, 2000)
    assembler.event({'type': 'input_audio_buffer.committed', 'item_id': 'a'})
    assembler.event({'type': 'input_audio_buffer.committed', 'item_id': 'b'})
    partial = {'type': 'conversation.item.input_audio_transcription.delta', 'event_id': 'delta1', 'item_id': 'a', 'delta': 'unit partial'}
    assert assembler.event(partial)[0]['text'] == 'unit partial'
    assert assembler.event(partial) == []
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(TranscriptSegment)) == 0
    assembler.event({'type': 'conversation.item.input_audio_transcription.completed', 'item_id': 'b', 'transcript': 'second unit event'})
    completed = {'type': 'conversation.item.input_audio_transcription.completed', 'item_id': 'a', 'transcript': 'first unit event'}
    assembler.event(completed); assert assembler.event(completed) == []
    result = client.get(f"/sessions/{identifier}/transcript-segments", headers={'X-Dev-User-Id': user}).json()
    assert [item['text'] for item in result] == ['first unit event', 'second unit event']
    assert [item['sequence'] for item in result] == [0, 1]
    assert assembler.pending() == 0
    with pytest.raises(ValueError, match='CONFLICT'):
        assembler.event({**completed, 'transcript': 'changed'})
    assert client.get(f"/sessions/{identifier}/transcript-segments", headers={'X-Dev-User-Id': other}).status_code == 404
    assert client.post(f"/sessions/{identifier}/transcript-segments", headers={'X-Dev-User-Id': user}, json={'text': 'forged'}).status_code == 405


def test_completion_before_ack_and_empty_event(materials):
    _, factory, user, _, session, _ = materials
    identifier = UUID(session['id'])
    with factory() as db:
        connection = TranscriptionConnection(session_id=identifier); db.add(connection); db.commit(); connection_id = connection.id
    assembler = TranscriptAssembler(factory, identifier, connection_id, user)
    assembler.reserve(0, 1000)
    assert assembler.event({'type': 'conversation.item.input_audio_transcription.completed', 'item_id': 'a', 'transcript': 'unit completion'}) == []
    assert assembler.event({'type': 'input_audio_buffer.committed', 'item_id': 'a'})[0]['type'] == 'transcript.final'
    assembler.reserve(1000, 2000); assembler.event({'type': 'input_audio_buffer.committed', 'item_id': 'b'})
    assert assembler.event({'type': 'conversation.item.input_audio_transcription.completed', 'item_id': 'b', 'transcript': ''}) == []
    assert assembler.pending() == 0


def test_single_use_expired_and_owner_scoped_tickets(materials, monkeypatch):
    client, factory, user, other, session, _ = materials
    begin(client, user, session)
    monkeypatch.setattr(type(get_settings()), 'ai_key', lambda self: SecretStr('unit-sentinel'))
    route = f"/sessions/{session['id']}/transcription-token"
    assert client.post(route, headers={'X-Dev-User-Id': other}).status_code == 404
    ticket = client.post(route, headers={'X-Dev-User-Id': user}).json()
    assert consume_ticket(factory, UUID(session['id']), ticket['token'])[0] == user
    with pytest.raises(ValueError): consume_ticket(factory, UUID(session['id']), ticket['token'])
    expired = client.post(route, headers={'X-Dev-User-Id': user}).json()
    with factory() as db:
        import hashlib
        row = db.get(TranscriptionTicket, hashlib.sha256(expired['token'].encode()).hexdigest()); row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1); db.commit()
    with pytest.raises(ValueError): consume_ticket(factory, UUID(session['id']), expired['token'])
