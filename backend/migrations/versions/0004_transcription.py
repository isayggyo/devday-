"""Single-use relay grants, provider turn ordering, committed transcripts."""
from alembic import op
import sqlalchemy as sa

revision = "0004_transcription"
down_revision = "0003_audio"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("transcription_tickets",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("lecture_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(100), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_transcription_tickets_session_id", "transcription_tickets", ["session_id"])
    op.create_table("transcription_connections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("lecture_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("provider_session_id", sa.String(200)),
        sa.Column("error_code", sa.String(80)),
    )
    op.create_index("ix_transcription_connections_session_id", "transcription_connections", ["session_id"])
    op.create_table("transcription_turns",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("lecture_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("connection_id", sa.Uuid(), sa.ForeignKey("transcription_connections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("provider_item_id", sa.String(200)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_code", sa.String(80)),
        sa.UniqueConstraint("session_id", "sequence", name="transcription_turn_sequence"),
        sa.UniqueConstraint("connection_id", "provider_item_id", name="transcription_provider_item"),
    )
    op.create_index("ix_transcription_turns_session_id", "transcription_turns", ["session_id"])
    op.create_table("transcript_segments",
        sa.Column("id", sa.Uuid(), sa.ForeignKey("transcription_turns.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("lecture_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("session_id", "sequence", name="transcript_segment_sequence"),
        sa.CheckConstraint("length(text) > 0 AND revision > 0 AND start_ms >= 0 AND end_ms >= start_ms", name="transcript_bounds"),
    )
    op.create_index("ix_transcript_segments_session_id", "transcript_segments", ["session_id"])


def downgrade():
    for table in ["transcript_segments", "transcription_turns", "transcription_connections", "transcription_tickets"]:
        op.drop_table(table)
