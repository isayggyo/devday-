from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0005_notes'
down_revision = '0004_transcription'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('live_notes', sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('session_id', sa.Uuid(), sa.ForeignKey('lecture_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('start_ms', sa.Integer(), nullable=False), sa.Column('end_ms', sa.Integer(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False), sa.Column('transcript_segment_ids', JSONB(), nullable=False),
        sa.Column('source_refs', JSONB(), nullable=False), sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False), sa.Column('last_sequence', sa.Integer(), nullable=False),
        sa.Column('error_code', sa.String(80)), sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index('ix_live_notes_session_id', 'live_notes', ['session_id'])

def downgrade(): op.drop_table('live_notes')
