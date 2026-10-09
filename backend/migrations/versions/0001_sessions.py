"""Persistent owner-scoped lecture sessions."""
from alembic import op
import sqlalchemy as sa

revision = "0001_sessions"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("lecture_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("user_id", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("test_run_id", sa.String(200)),
        sa.CheckConstraint("status IN ('created','preparing','recording','finalizing','processing','completed','failed')", name="session_status"),
    )
    op.create_index("ix_lecture_sessions_user_id", "lecture_sessions", ["user_id"])


def downgrade():
    op.drop_table("lecture_sessions")
