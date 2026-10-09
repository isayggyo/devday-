"""Trusted provider events only; partials never become committed transcript records."""
import asyncio
import base64
from collections import deque
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import secrets
import struct
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select, func, update
from sqlalchemy.orm import Session

from .auth import current_user
from .config import get_settings
from .db import database_session, session_factory
from .models import TranscriptSegment, TranscriptionTicket, TranscriptionConnection, TranscriptionTurn
from .session_manager import owned_session
from .realtime_provider import transcription_connection, ProviderError

router = APIRouter(prefix="/sessions/{session_id}", tags=["transcription"])


def segment_view(row):
    return {"id": str(row.id), "sessionId": str(row.session_id), "sequence": row.sequence, "startMs": row.start_ms, "endMs": row.end_ms,
        "text": row.text, "revision": row.revision, "committedAt": row.committed_at.astimezone(timezone.utc).isoformat(), "status": "final"}


@router.get("/transcript-segments")
def list_segments(session_id: UUID, user: str = Depends(current_user), db: Session = Depends(database_session)):
    owned_session(db, session_id, user)
    return [segment_view(row) for row in db.scalars(select(TranscriptSegment).where(TranscriptSegment.session_id == session_id).order_by(TranscriptSegment.sequence)).all()]


@router.post("/transcription-token")
def create_ticket(session_id: UUID, user: str = Depends(current_user), db: Session = Depends(database_session)):
    item = owned_session(db, session_id, user)
    if item.status not in {"recording", "finalizing"}:
        raise HTTPException(409, {"code": "NOT_RECORDING", "message": "녹음을 먼저 시작해 주세요."})
    if not get_settings().ai_key().get_secret_value():
        raise HTTPException(503, {"code": "AI_NOT_CONFIGURED", "message": "전사 API 키가 설정되지 않았습니다. 원본 녹음은 유지됩니다."})
    token = secrets.token_urlsafe(32)
    db.add(TranscriptionTicket(token_hash=hashlib.sha256(token.encode()).hexdigest(), session_id=session_id, user_id=user, expires_at=datetime.now(timezone.utc) + timedelta(seconds=60), consumed=False))
    db.commit()
    return {"token": token, "expiresIn": 60, "path": f"/sessions/{session_id}/transcription"}


def consume_ticket(factory, session_id, token):
    with factory() as db:
        ticket = db.scalar(select(TranscriptionTicket).where(TranscriptionTicket.token_hash == hashlib.sha256(token.encode()).hexdigest()).with_for_update())
        if not ticket or ticket.session_id != session_id or ticket.consumed or ticket.expires_at < datetime.now(timezone.utc):
            raise ValueError("INVALID_TICKET")
        owned_session(db, session_id, ticket.user_id)
        ticket.consumed = True
        connection = TranscriptionConnection(session_id=session_id)
        db.add(connection)
        db.commit()
        after = db.scalar(select(func.coalesce(func.max(TranscriptSegment.end_ms), 0)).where(TranscriptSegment.session_id == session_id))
        return ticket.user_id, connection.id, after


class TranscriptAssembler:
    def __init__(self, factory, session_id, connection_id, user):
        self.factory, self.session_id, self.connection_id, self.user = factory, session_id, connection_id, user
        self.waiting = deque()
        self.items = {}
        self.partials = {}
        self.deferred = {}
        self.seen = set()

    def reserve(self, start, end):
        with self.factory() as db:
            owned_session(db, self.session_id, self.user, lock=True)
            sequence = db.scalar(select(func.coalesce(func.max(TranscriptionTurn.sequence), -1)).where(TranscriptionTurn.session_id == self.session_id)) + 1
            row = TranscriptionTurn(session_id=self.session_id, connection_id=self.connection_id, sequence=sequence, start_ms=start, end_ms=end)
            db.add(row); db.commit()
            self.waiting.append(row.id)

    def event(self, event):
        event_id = event.get("event_id")
        if event_id and event_id in self.seen:
            return []
        if event_id:
            self.seen.add(event_id)
        kind, item = event.get("type"), event.get("item_id")
        if kind == "input_audio_buffer.committed":
            if item in self.items:
                return []
            if not self.waiting:
                raise ValueError("UNMATCHED_COMMIT")
            identifier = self.waiting.popleft(); self.items[item] = identifier
            with self.factory() as db:
                row = db.get(TranscriptionTurn, identifier); row.provider_item_id = item; db.commit()
            deferred = self.deferred.pop(item, None)
            return self.complete(item, deferred) if deferred is not None else []
        if kind == "conversation.item.input_audio_transcription.delta":
            self.partials[item] = self.partials.get(item, "") + event.get("delta", "")
            return [{"type": "transcript.partial", "itemId": item, "text": self.partials[item]}]
        if kind == "conversation.item.input_audio_transcription.completed":
            text = event.get("transcript", "").strip()
            if item not in self.items:
                self.deferred[item] = text
                return []
            return self.complete(item, text)
        if kind == "conversation.item.input_audio_transcription.failed":
            if item in self.items:
                with self.factory() as db:
                    row = db.get(TranscriptionTurn, self.items[item]); row.status = "failed"; row.error_code = "STT_TURN_FAILED"; db.commit()
            return [{"type": "stt.warning", "message": "일부 발화 전사에 실패했습니다. 원본 음성은 보관됩니다."}]
        return []

    def complete(self, item, text):
        with self.factory() as db:
            turn = db.get(TranscriptionTurn, self.items[item])
            existing = db.get(TranscriptSegment, turn.id)
            if existing:
                if existing.text != text:
                    raise ValueError("TRANSCRIPT_CONFLICT")
                return []
            if not text:
                turn.status = "empty"; db.commit(); return []
            segment = TranscriptSegment(id=turn.id, session_id=self.session_id, sequence=turn.sequence, start_ms=turn.start_ms, end_ms=turn.end_ms, text=text, revision=1)
            db.add(segment); turn.status = "committed"; db.commit(); db.refresh(segment)
            self.partials.pop(item, None)
            return [{"type": "transcript.final", "itemId": item, "segment": segment_view(segment)}]

    def pending(self):
        with self.factory() as db:
            return db.scalar(select(func.count()).select_from(TranscriptionTurn).where(TranscriptionTurn.connection_id == self.connection_id, TranscriptionTurn.status == "pending"))


@router.websocket("/transcription")
async def stream_transcription(socket: WebSocket, session_id: UUID, token: str):
    if socket.headers.get("origin") != get_settings().frontend_origin:
        await socket.close(code=1008); return
    factory = session_factory()
    try:
        user, connection_id, after = await asyncio.to_thread(consume_ticket, factory, session_id, token)
    except Exception:
        await socket.close(code=1008); return
    await socket.accept()
    assembler = TranscriptAssembler(factory, session_id, connection_id, user)
    receive_task = None
    finalized = False
    start = None; last = after; last_speech = None; speech = False

    def connection_status(status, provider=None, error=None):
        with factory() as db:
            row = db.get(TranscriptionConnection, connection_id); row.status = status; row.error_code = error
            if provider: row.provider_session_id = provider
            if status != "connected":
                db.execute(update(TranscriptionTurn).where(TranscriptionTurn.connection_id == connection_id, TranscriptionTurn.status == "pending").values(status="failed", error_code=error or "STT_INTERRUPTED"))
            db.commit()

    try:
        async with transcription_connection(user) as (provider, provider_id):
            await asyncio.to_thread(connection_status, "connected", provider_id)
            await socket.send_json({"type": "stt.ready", "afterMs": after})

            async def provider_events():
                try:
                    async for message in provider:
                        event = json.loads(message)
                        if event.get("type") == "error":
                            raise ProviderError("STT_PROVIDER_ERROR")
                        messages = await asyncio.to_thread(assembler.event, event)
                        for payload in messages:
                            await socket.send_json(payload)
                except Exception:
                    await socket.close(code=1011)

            receive_task = asyncio.create_task(provider_events())

            async def commit():
                nonlocal start, speech, last_speech
                if start is not None and speech and last - start >= 100:
                    await asyncio.to_thread(assembler.reserve, start, last)
                    await provider.send(json.dumps({"type": "input_audio_buffer.commit"}))
                else:
                    await provider.send(json.dumps({"type": "input_audio_buffer.clear"}))
                start = None; speech = False; last_speech = None

            while True:
                message = await socket.receive()
                if message["type"] == "websocket.disconnect":
                    break
                data = message.get("bytes")
                if data:
                    if len(data) < 10 or (len(data) - 8) % 2 or len(data) > 100000:
                        raise ValueError("INVALID_PCM_PACKET")
                    begin, end = struct.unpack_from("<II", data)
                    pcm = data[8:]
                    if end <= after: continue
                    if begin < after:
                        pcm = pcm[min(len(pcm), (after - begin) * 48):]; begin = after
                    if begin < last - 3 or end < begin or end > 36_000_000:
                        raise ValueError("INVALID_PCM_TIMELINE")
                    last = end
                    if start is None: start = begin
                    values = struct.unpack("<" + "h" * (len(pcm) // 2), pcm)
                    rms = math.sqrt(sum(value * value for value in values) / max(1, len(values))) / 32768
                    if rms > 0.008: speech = True; last_speech = end
                    await provider.send(json.dumps({"type": "input_audio_buffer.append", "audio": base64.b64encode(pcm).decode()}))
                    if (speech and ((end - (last_speech or end) >= 650) or end - start >= get_settings().stt_commit_max_ms)) or (not speech and end - start >= 10000):
                        await commit()
                elif message.get("text"):
                    control = json.loads(message["text"])
                    if control.get("type") == "finish":
                        await commit()
                        deadline = asyncio.get_running_loop().time() + 20
                        while await asyncio.to_thread(assembler.pending):
                            if asyncio.get_running_loop().time() > deadline:
                                raise ProviderError("STT_FINALIZE_TIMEOUT")
                            await asyncio.sleep(0.1)
                        finalized = True
                        await socket.send_json({"type": "stt.finalized"})
                        break
    except WebSocketDisconnect:
        pass
    except Exception as error:
        code = error.code if isinstance(error, ProviderError) else "STT_STREAM_INTERRUPTED"
        try: await socket.send_json({"type": "stt.error", "code": code, "message": "전사 연결에 실패했습니다. 원본 녹음은 유지됩니다."})
        except Exception: pass
    finally:
        if receive_task:
            receive_task.cancel(); await asyncio.gather(receive_task, return_exceptions=True)
        await asyncio.to_thread(connection_status, "finalized" if finalized else "interrupted")
        try: await socket.close()
        except Exception: pass
