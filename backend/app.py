"""App shell and isolated test-session lifecycle; no fabricated AI output."""

import os
from backend import logging_filter
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Response, Depends, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.config import get_settings
from backend.db import ping_database
from backend.errors import install_error_handlers
from backend.auth import current_user
from backend.db import database_session
from backend.models import LectureSession
from backend.session_manager import router as session_router, owned_session
from backend.materials import router as material_router, upload as upload_material, document_view
from backend.storage import get_object_store, ObjectStore
from backend.models import MaterialDocument, MaterialPage
from sqlalchemy import select
from sqlalchemy import func
from backend.audio import router as audio_router, StartCapture, StopCapture, start_recording as start_capture, stop_recording as stop_capture
from backend.models import AudioChunk
from backend.transcription import router as transcription_router, list_segments
from backend.notes import router as notes_router
from backend.questions import router as questions_router
from backend.visuals import router as visuals_router
from sqlalchemy.orm import Session
from uuid import UUID

app = FastAPI(title="Lecture app baseline")
app.include_router(session_router)
app.include_router(material_router)
app.include_router(audio_router)
app.include_router(transcription_router)
app.include_router(notes_router)
app.include_router(questions_router)
app.include_router(visuals_router)
install_error_handlers(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().frontend_origin],
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "X-Dev-User-Id", "X-E2E-Run-Id"],
)

# These flags describe product implementation, not the browser's media support.
CAPABILITIES = {
    "upload": True,
    "recording": True,
    "transcription": True,
    "slides": False,
    "provenance": False,
    "session_end": False,
}


class TestSession(BaseModel):
    run_id: str = Field(min_length=1, max_length=200)


def require_e2e():
    if not get_settings().e2e_mode:
        raise HTTPException(404, "E2E session controls are disabled")


def session_by_id(session_id: UUID, user: str = Depends(current_user), db: Session = Depends(database_session)):
    return owned_session(db, session_id, user)


def not_implemented(feature: str):
    raise HTTPException(501, {"code": "NOT_IMPLEMENTED", "feature": feature})


@app.get("/health")
def health():
    try:
        ping_database()
    except Exception:
        raise HTTPException(503, {"code": "DATABASE_UNAVAILABLE", "message": "PostgreSQL is unavailable"})
    settings = get_settings()
    return {"status": "ok", "service": "lecture-backend", "database": "ok", "auth_mode": settings.auth_mode, "e2e_enabled": settings.e2e_mode}


@app.get("/api/capabilities")
def capabilities():
    return CAPABILITIES


@app.post("/api/e2e/sessions", status_code=201)
def create_test_session(request: TestSession, user: str = Depends(current_user), db: Session = Depends(database_session)):
    require_e2e()
    item = LectureSession(title="E2E lecture", user_id=user, test_run_id=request.run_id)
    db.add(item)
    db.commit()
    db.refresh(item)
    session = {
        "id": str(item.id),
        "run_id": request.run_id,
        "state": "idle",
        "documents": [],
        "transcripts": [],
        "slides": [],
        "audio_bytes": 0,
    }
    return session


@app.get("/api/sessions/{session_id}")
def get_session(item: LectureSession = Depends(session_by_id), db: Session = Depends(database_session)):
    documents = [document_view(db, document) for document in db.scalars(select(MaterialDocument).where(MaterialDocument.session_id == item.id)).all()]
    audio_bytes = db.scalar(select(func.coalesce(func.sum(AudioChunk.byte_length), 0)).where(AudioChunk.session_id == item.id))
    state = "idle" if item.status in {"created", "preparing"} else "stopped" if item.status == "finalizing" else "ended" if item.status == "completed" else item.status
    return {"id": str(item.id), "run_id": item.test_run_id, "state": state, "documents": documents, "transcripts": list_segments(item.id, item.user_id, db), "slides": [], "audio_bytes": audio_bytes}


@app.delete("/api/e2e/sessions/{session_id}", status_code=204)
def delete_test_session(item: LectureSession = Depends(session_by_id), db: Session = Depends(database_session)):
    require_e2e()
    if not item.test_run_id:
        raise HTTPException(404, "Test session not found")
    get_object_store().delete_prefix(f"sessions/{item.id}/")
    db.delete(item)
    db.commit()
    return Response(status_code=204)


@app.post("/api/sessions/{session_id}/documents")
def upload_document(session_id: UUID, file: UploadFile = File(...), user: str = Depends(current_user), db: Session = Depends(database_session), store: ObjectStore = Depends(get_object_store)):
    return upload_material(session_id, file, user, db, store)


@app.post("/api/sessions/{session_id}/recording/start")
def start_recording(session_id: UUID, request: StartCapture, user: str = Depends(current_user), db: Session = Depends(database_session)):
    return start_capture(session_id, request, user, db)


@app.get("/api/sessions/{session_id}/transcripts")
def transcripts(item: LectureSession = Depends(session_by_id), db: Session = Depends(database_session)):
    return [segment | {'session_id': segment['sessionId']} for segment in list_segments(item.id, item.user_id, db)]


@app.get("/api/sessions/{session_id}/slides")
def slides(item: LectureSession = Depends(session_by_id)):
    not_implemented("slides")


@app.get("/api/sessions/{session_id}/slides/{slide_id}")
def slide(slide_id: str, item: LectureSession = Depends(session_by_id)):
    not_implemented("provenance")


@app.post("/api/sessions/{session_id}/recording/stop")
def stop_recording(session_id: UUID, request: StopCapture, user: str = Depends(current_user), db: Session = Depends(database_session)):
    return stop_capture(session_id, request, user, db)


@app.post("/api/sessions/{session_id}/end")
def end_session(item: LectureSession = Depends(session_by_id)):
    not_implemented("session_end")
