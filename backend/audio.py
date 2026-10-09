import hashlib
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from .auth import current_user
from .db import database_session
from .models import AudioChunk, MaterialDocument
from .session_manager import owned_session, transition, SessionView
from .storage import ObjectStore, get_object_store

router = APIRouter(prefix="/sessions/{session_id}", tags=["audio"])


class StartCapture(BaseModel):
    captureId: UUID


class StopCapture(BaseModel):
    captureId: UUID | None = None


def chunk_view(chunk):
    return {"id": str(chunk.id), "sessionId": str(chunk.session_id), "captureId": str(chunk.capture_id), "sequence": chunk.sequence,
        "startMs": chunk.start_ms, "endMs": chunk.end_ms, "byteLength": chunk.byte_length, "mimeType": chunk.mime_type, "sha256": chunk.sha256}


@router.post("/recording/start")
def start_recording(session_id: UUID, request: StartCapture, user: str = Depends(current_user), db: Session = Depends(database_session)):
    session = owned_session(db, session_id, user, lock=True)
    if session.status == "recording" and session.capture_id == request.captureId:
        return SessionView.model_validate(session).model_dump(by_alias=True, mode="json")
    if session.status not in {"created", "preparing"}:
        raise HTTPException(409, {"code": "RECORDING_ALREADY_ACTIVE", "message": "기존 녹음을 중지하거나 세션 상태를 복구해 주세요."})
    if db.scalar(select(MaterialDocument.id).where(MaterialDocument.session_id == session_id, MaterialDocument.processing_status.in_(["processing", "failed"]))):
        raise HTTPException(409, {"code": "MATERIALS_NOT_READY", "message": "자료 처리를 완료한 후 녹음을 시작해 주세요."})
    if session.status == "created":
        transition(db, session_id, user, "preparing")
    session.capture_id = request.captureId
    transition(db, session_id, user, "recording")
    db.commit()
    return SessionView.model_validate(session).model_dump(by_alias=True, mode="json")


@router.post("/recording/stop")
def stop_recording(session_id: UUID, request: StopCapture, user: str = Depends(current_user), db: Session = Depends(database_session)):
    session = owned_session(db, session_id, user, lock=True)
    if request.captureId and request.captureId != session.capture_id:
        raise HTTPException(409, {"code": "CAPTURE_MISMATCH", "message": "다른 녹음 요청입니다."})
    if session.status == "recording":
        transition(db, session_id, user, "finalizing")
        db.commit()
    elif session.status != "finalizing":
        raise HTTPException(409, {"code": "NOT_RECORDING", "message": "진행 중인 녹음이 없습니다."})
    return SessionView.model_validate(session).model_dump(by_alias=True, mode="json")


@router.post("/audio/chunks", status_code=201)
def upload_chunk(session_id: UUID, chunk_id: UUID = Form(...), capture_id: UUID = Form(...), sequence: int = Form(..., ge=0), start_ms: int = Form(..., ge=0), end_ms: int = Form(..., ge=0), file: UploadFile = File(...), user: str = Depends(current_user), db: Session = Depends(database_session), store: ObjectStore = Depends(get_object_store)):
    session = owned_session(db, session_id, user, lock=True)
    if session.status not in {"recording", "finalizing"} or capture_id != session.capture_id:
        raise HTTPException(409, {"code": "CAPTURE_CLOSED", "message": "이 녹음에 청크를 업로드할 수 없습니다."})
    data = file.file.read(16 * 1024 * 1024 + 1)
    mime = (file.content_type or "").split(";")[0].strip().lower()
    if mime not in {"audio/webm", "audio/ogg", "audio/mp4", "audio/wav"} or not 0 < len(data) <= 16 * 1024 * 1024 or end_ms < start_ms or end_ms > 36_000_000:
        raise HTTPException(400, {"code": "INVALID_AUDIO_CHUNK", "message": "음성 청크 형식·크기·시간 정보가 올바르지 않습니다."})
    digest = hashlib.sha256(data).hexdigest()
    existing = db.get(AudioChunk, chunk_id)
    if existing:
        if (existing.session_id, existing.capture_id, existing.sequence, existing.sha256, existing.start_ms, existing.end_ms, existing.mime_type) != (session_id, capture_id, sequence, digest, start_ms, end_ms, mime):
            raise HTTPException(409, {"code": "CHUNK_CONFLICT", "message": "동일 청크 ID의 내용이 다릅니다."})
        return {**chunk_view(existing), "deduplicated": True}
    if db.scalar(select(AudioChunk.id).where(AudioChunk.session_id == session_id, AudioChunk.sequence == sequence)):
        raise HTTPException(409, {"code": "SEQUENCE_CONFLICT", "message": "동일 순서의 다른 청크가 이미 저장됐습니다."})
    existing_mime = db.scalar(select(AudioChunk.mime_type).where(AudioChunk.session_id == session_id).limit(1))
    if existing_mime and existing_mime != mime:
        raise HTTPException(400, {"code": "AUDIO_FORMAT_CHANGED", "message": "같은 녹음의 청크 형식이 변경됐습니다."})
    # MediaRecorder fragments after the first chunk need not contain container headers.
    if sequence == 0:
        valid = ((mime == "audio/webm" and data.startswith(b"\x1aE\xdf\xa3")) or (mime == "audio/ogg" and data.startswith(b"OggS"))
            or (mime == "audio/mp4" and data[4:8] == b"ftyp") or (mime == "audio/wav" and data.startswith(b"RIFF") and data[8:12] == b"WAVE"))
        if not valid:
            raise HTTPException(400, {"code": "INVALID_AUDIO_CONTAINER", "message": "첫 음성 청크의 형식이 올바르지 않습니다."})
    key = f"sessions/{session_id}/audio/{capture_id}/{sequence:08d}-{chunk_id}"
    try:
        store.put(key, data, mime)
    except Exception:
        raise HTTPException(503, {"code": "OBJECT_STORAGE_UNAVAILABLE", "message": "음성 전송에 실패했습니다. 로컬 백업을 유지하고 다시 시도해 주세요."}) from None
    item = AudioChunk(id=chunk_id, session_id=session_id, capture_id=capture_id, sequence=sequence, start_ms=start_ms, end_ms=end_ms,
        byte_length=len(data), mime_type=mime, sha256=digest, object_ref=key)
    db.add(item)
    try:
        db.commit()
    except Exception:
        db.rollback()
        store.delete(key)
        raise
    return {**chunk_view(item), "deduplicated": False}


@router.get("/audio")
def audio_status(session_id: UUID, user: str = Depends(current_user), db: Session = Depends(database_session)):
    session = owned_session(db, session_id, user)
    chunks = db.scalars(select(AudioChunk).where(AudioChunk.session_id == session_id).order_by(AudioChunk.sequence)).all()
    return {"captureId": str(session.capture_id) if session.capture_id else None, "chunks": [chunk_view(chunk) for chunk in chunks], "byteLength": sum(chunk.byte_length for chunk in chunks)}


@router.get("/audio/file")
def original_recording(session_id: UUID, user: str = Depends(current_user), db: Session = Depends(database_session), store: ObjectStore = Depends(get_object_store)):
    owned_session(db, session_id, user)
    chunks = db.scalars(select(AudioChunk).where(AudioChunk.session_id == session_id).order_by(AudioChunk.sequence)).all()
    if not chunks:
        raise HTTPException(404, {"code": "AUDIO_NOT_FOUND", "message": "저장된 음성이 없습니다."})
    if [chunk.sequence for chunk in chunks] != list(range(len(chunks))):
        raise HTTPException(409, {"code": "AUDIO_INCOMPLETE", "message": "미전송 음성 청크를 먼저 재전송해 주세요."})
    return StreamingResponse((store.get(chunk.object_ref) for chunk in chunks), media_type=chunks[0].mime_type)
