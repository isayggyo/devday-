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
