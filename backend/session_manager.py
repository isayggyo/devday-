from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Header, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, field_serializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import current_user
from .db import database_session
from .models import LectureSession, MaterialDocument
from .config import get_settings
from .storage import ObjectStore, get_object_store

TRANSITIONS = {
    "created": {"preparing", "failed"},
    "preparing": {"recording", "failed"},
    "recording": {"finalizing", "failed"},
    "finalizing": {"processing", "failed"},
    "processing": {"completed", "failed"},
    "completed": set(), "failed": set(),
}


class CreateSession(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    courseKey: str | None = Field(default=None, max_length=100)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Lecture title is required")
        return value


class SessionView(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: UUID
    title: str
    status: str
    user_id: str = Field(serialization_alias="userId")
    created_at: datetime = Field(serialization_alias="createdAt")
    started_at: datetime | None = Field(serialization_alias="startedAt")
    ended_at: datetime | None = Field(serialization_alias="endedAt")
    course_key: str | None = Field(default=None, serialization_alias='courseKey')
    recording_input: dict | None = Field(default=None, serialization_alias='recordingInput')

    @field_serializer("created_at", "started_at", "ended_at")
    def utc_time(self, value):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value else None


def owned_session(db: Session, session_id: UUID, user_id: str, *, lock=False):
    query = select(LectureSession).where(LectureSession.id == session_id, LectureSession.user_id == user_id)
    if lock:
        query = query.with_for_update()
    item = db.scalar(query)
    if item is None:
        raise HTTPException(404, {"code": "SESSION_NOT_FOUND", "message": "Lecture session not found"})
    return item


def transition(db: Session, session_id: UUID, user_id: str, target: str):
    item = owned_session(db, session_id, user_id, lock=True)
    if target not in TRANSITIONS[item.status]:
        raise HTTPException(409, {"code": "INVALID_SESSION_TRANSITION", "message": f"Cannot change {item.status} to {target}"})
    item.status = target
    now = datetime.now(timezone.utc)
    if target == "recording":
        item.started_at = now
    if target == "finalizing" or (target == "failed" and item.started_at):
        item.ended_at = now
    db.flush()
    return item


router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionView, status_code=201)
def create_session(request: CreateSession, user: str = Depends(current_user), db: Session = Depends(database_session), x_e2e_run_id: str | None = Header(default=None, max_length=200)):
    item = LectureSession(title=request.title, user_id=user, course_key=(request.courseKey or '').strip() or None, test_run_id=x_e2e_run_id if get_settings().e2e_mode else None)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("", response_model=list[SessionView])
def list_sessions(user: str = Depends(current_user), db: Session = Depends(database_session)):
    return db.scalars(select(LectureSession).where(LectureSession.user_id == user).order_by(LectureSession.created_at.desc())).all()


@router.get("/{session_id}", response_model=SessionView)
def get_session(session_id: UUID, user: str = Depends(current_user), db: Session = Depends(database_session)):
    return owned_session(db, session_id, user)


@router.delete('/{session_id}', status_code=204)
def delete_session(session_id: UUID, user: str = Depends(current_user), db: Session = Depends(database_session), store: ObjectStore = Depends(get_object_store)):
    item = owned_session(db, session_id, user, lock=True)
    if item.status in {'recording', 'processing'}:
        raise HTTPException(409, {'code': 'SESSION_BUSY', 'message': '녹음 또는 슬라이드 생성 작업을 마친 뒤 삭제해 주세요.'})
    if db.scalar(select(MaterialDocument.id).where(MaterialDocument.session_id == session_id, MaterialDocument.processing_status == 'processing').limit(1)):
        raise HTTPException(409, {'code': 'MATERIAL_PROCESSING', 'message': '강의자료 처리가 끝난 뒤 삭제해 주세요.'})
    try:
        store.delete_prefix(f'sessions/{item.id}/')
    except Exception:
        raise HTTPException(503, {'code': 'SESSION_DELETE_FAILED', 'message': '저장 파일 삭제를 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.'}) from None
    # Existing foreign keys cascade to materials, audio, transcripts, notes and Q&A.
    db.delete(item)
    db.commit()
    return Response(status_code=204)


class CourseLink(BaseModel):
    courseKey: str | None = Field(default=None, max_length=100)


@router.patch('/{session_id}/course', response_model=SessionView)
def link_course(session_id: UUID, request: CourseLink, user: str = Depends(current_user), db: Session = Depends(database_session)):
    session = owned_session(db, session_id, user, lock=True)
    if session.status == 'processing': raise HTTPException(409, {'code': 'SYNTHESIS_RUNNING', 'message': '생성 작업이 끝난 뒤 과목 연결을 변경해 주세요.'})
    session.course_key = (request.courseKey or '').strip() or None; db.commit()
    return session


class ChangeSession(BaseModel):
    # Recording/finalization transitions belong to their actual pipelines, never an arbitrary client patch.
    status: Literal["preparing", "failed"]


@router.patch("/{session_id}", response_model=SessionView)
def change_session(session_id: UUID, request: ChangeSession, user: str = Depends(current_user), db: Session = Depends(database_session)):
    item = transition(db, session_id, user, request.status)
    db.commit()
    return item
