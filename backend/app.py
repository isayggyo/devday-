"""App shell and isolated test-session lifecycle; no fabricated AI output."""

import os
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.config import get_settings
from backend.db import ping_database
from backend.errors import install_error_handlers

app = FastAPI(title="Lecture app baseline")
install_error_handlers(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().frontend_origin],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "X-Dev-User-Id"],
)

# These flags describe product implementation, not the browser's media support.
CAPABILITIES = {
    "upload": False,
    "recording": False,
    "transcription": False,
    "slides": False,
    "provenance": False,
    "session_end": False,
}
sessions: dict[str, dict] = {}


class TestSession(BaseModel):
    run_id: str = Field(min_length=1, max_length=200)


def require_e2e():
    if not get_settings().e2e_mode:
        raise HTTPException(404, "E2E session controls are disabled")


def session_by_id(session_id: str):
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")
    return sessions[session_id]


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
def create_test_session(request: TestSession):
    require_e2e()
    session_id = str(uuid4())
    session = {
        "id": session_id,
        "run_id": request.run_id,
        "state": "idle",
        "documents": [],
        "transcripts": [],
        "slides": [],
        "audio_bytes": 0,
    }
    sessions[session_id] = session
    return session


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    return session_by_id(session_id)


@app.delete("/api/e2e/sessions/{session_id}", status_code=204)
def delete_test_session(session_id: str):
    require_e2e()
    session_by_id(session_id)
    del sessions[session_id]
    return Response(status_code=204)


@app.post("/api/sessions/{session_id}/documents")
def upload_document(session_id: str):
    session_by_id(session_id)
    not_implemented("upload")


@app.post("/api/sessions/{session_id}/recording/start")
def start_recording(session_id: str):
    session_by_id(session_id)
    not_implemented("recording")


@app.get("/api/sessions/{session_id}/transcripts")
def transcripts(session_id: str):
    session_by_id(session_id)
    not_implemented("transcription")


@app.get("/api/sessions/{session_id}/slides")
def slides(session_id: str):
    session_by_id(session_id)
    not_implemented("slides")


@app.get("/api/sessions/{session_id}/slides/{slide_id}")
def slide(session_id: str, slide_id: str):
    session_by_id(session_id)
    not_implemented("provenance")


@app.post("/api/sessions/{session_id}/recording/stop")
def stop_recording(session_id: str):
    session_by_id(session_id)
    not_implemented("recording")


@app.post("/api/sessions/{session_id}/end")
def end_session(session_id: str):
    session_by_id(session_id)
    not_implemented("session_end")
