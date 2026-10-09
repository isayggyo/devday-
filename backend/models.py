from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, String, func, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class LectureSession(Base):
    __tablename__ = "lecture_sessions"
    __table_args__ = (CheckConstraint("status IN ('created','preparing','recording','finalizing','processing','completed','failed')", name="session_status"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="created")
    user_id: Mapped[str] = mapped_column(String(100), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    test_run_id: Mapped[str | None] = mapped_column(String(200))
    capture_id: Mapped[UUID | None] = mapped_column()


class MaterialDocument(Base):
    __tablename__ = "material_documents"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("lecture_sessions.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(240))
    file_type: Mapped[str] = mapped_column(String(10))
    revision: Mapped[int] = mapped_column(default=1)
    processing_status: Mapped[str] = mapped_column(String(30), default="processing")
    original_ref: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(60))


class MaterialPage(Base):
    __tablename__ = "material_pages"
    __table_args__ = (UniqueConstraint("document_id", "page_number", name="material_page_number"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("material_documents.id", ondelete="CASCADE"), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column()
    description: Mapped[str] = mapped_column()
    image_ref: Mapped[str] = mapped_column(String(500))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB)


class AudioChunk(Base):
    __tablename__ = "audio_chunks"
    __table_args__ = (UniqueConstraint("session_id", "sequence", name="audio_chunk_sequence"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("lecture_sessions.id", ondelete="CASCADE"), index=True)
    capture_id: Mapped[UUID] = mapped_column()
    sequence: Mapped[int] = mapped_column(Integer)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    byte_length: Mapped[int] = mapped_column(Integer)
    mime_type: Mapped[str] = mapped_column(String(100))
    sha256: Mapped[str] = mapped_column(String(64))
    object_ref: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TranscriptionTicket(Base):
    __tablename__ = "transcription_tickets"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("lecture_sessions.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(String(100))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed: Mapped[bool] = mapped_column(default=False)


class TranscriptionConnection(Base):
    __tablename__ = "transcription_connections"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("lecture_sessions.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="connecting")
    provider_session_id: Mapped[str | None] = mapped_column(String(200))
    error_code: Mapped[str | None] = mapped_column(String(80))


class TranscriptionTurn(Base):
    __tablename__ = "transcription_turns"
    __table_args__ = (UniqueConstraint("session_id", "sequence", name="transcription_turn_sequence"), UniqueConstraint("connection_id", "provider_item_id", name="transcription_provider_item"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("lecture_sessions.id", ondelete="CASCADE"), index=True)
    connection_id: Mapped[UUID] = mapped_column(ForeignKey("transcription_connections.id", ondelete="CASCADE"))
    sequence: Mapped[int] = mapped_column(Integer)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    provider_item_id: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    error_code: Mapped[str | None] = mapped_column(String(80))


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"
    __table_args__ = (UniqueConstraint("session_id", "sequence", name="transcript_segment_sequence"),)
    id: Mapped[UUID] = mapped_column(ForeignKey("transcription_turns.id", ondelete="CASCADE"), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("lecture_sessions.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column()
    revision: Mapped[int] = mapped_column(default=1)
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LiveNote(Base):
    __tablename__ = "live_notes"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("lecture_sessions.id", ondelete="CASCADE"), index=True)
    start_ms: Mapped[int] = mapped_column(Integer, default=0)
    end_ms: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str] = mapped_column(default="")
    transcript_segment_ids: Mapped[list] = mapped_column(JSONB, default=list)
    source_refs: Mapped[list] = mapped_column(JSONB, default=list)
    revision: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(20), default="generating")
    last_sequence: Mapped[int] = mapped_column(Integer, default=-1)
    error_code: Mapped[str | None] = mapped_column(String(80))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContextSnapshot(Base):
    __tablename__ = 'context_snapshots'
    snapshot_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(ForeignKey('lecture_sessions.id', ondelete='CASCADE'), index=True)
    question_id: Mapped[UUID] = mapped_column(unique=True)
    transcript_high_watermark: Mapped[int] = mapped_column(Integer)
    material_revisions: Mapped[dict] = mapped_column(JSONB)
    frozen_blocks: Mapped[list] = mapped_column(JSONB)
    coverage: Mapped[dict] = mapped_column(JSONB)
    diagnostics: Mapped[list] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StudentQuestion(Base):
    __tablename__ = 'student_questions'
    __table_args__ = (UniqueConstraint('session_id', 'client_question_id', name='question_client_id'),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(ForeignKey('lecture_sessions.id', ondelete='CASCADE'), index=True)
    client_question_id: Mapped[UUID] = mapped_column()
    question_text: Mapped[str] = mapped_column()
    context_snapshot_id: Mapped[UUID] = mapped_column(ForeignKey('context_snapshots.snapshot_id', ondelete='CASCADE'))
    selected_page_ids: Mapped[list] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default='queued')
    error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GeneratedAnswer(Base):
    __tablename__ = 'generated_answers'
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    question_id: Mapped[UUID] = mapped_column(ForeignKey('student_questions.id', ondelete='CASCADE'), unique=True)
    answer: Mapped[str] = mapped_column()
    citations: Mapped[list] = mapped_column(JSONB)
    grounding_status: Mapped[str] = mapped_column(String(30))
    needs_visual: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VisualExplanation(Base):
    __tablename__ = 'visual_explanations'
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    answer_id: Mapped[UUID] = mapped_column(ForeignKey('generated_answers.id', ondelete='CASCADE'), unique=True)
    layout_type: Mapped[str | None] = mapped_column(String(30))
    requested_layout: Mapped[str | None] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(default='')
    elements: Mapped[dict] = mapped_column(JSONB, default=dict)
    source_refs: Mapped[list] = mapped_column(JSONB, default=list)
    revision: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(20), default='queued')
    error_code: Mapped[str | None] = mapped_column(String(80))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
