"""Durable recording capture identity and deduplicated object-storage chunks."""
from alembic import op
import sqlalchemy as sa

revision = "0003_audio"
down_revision = "0002_materials"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("lecture_sessions", sa.Column("capture_id", sa.Uuid()))
    op.create_table("audio_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("lecture_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("capture_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("byte_length", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("object_ref", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("session_id", "sequence", name="audio_chunk_sequence"),
        sa.CheckConstraint("sequence >= 0 AND start_ms >= 0 AND end_ms >= start_ms AND byte_length > 0", name="audio_chunk_bounds"),
    )
    op.create_index("ix_audio_chunks_session_id", "audio_chunks", ["session_id"])


def downgrade():
    op.drop_table("audio_chunks")
    op.drop_column("lecture_sessions", "capture_id")
