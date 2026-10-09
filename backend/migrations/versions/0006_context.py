from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0006_context'
down_revision = '0005_notes'
branch_labels = depends_on = None

def upgrade():
    op.create_table('context_snapshots', sa.Column('snapshot_id', sa.Uuid(), primary_key=True),
        sa.Column('session_id', sa.Uuid(), sa.ForeignKey('lecture_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('question_id', sa.Uuid(), nullable=False, unique=True),
        sa.Column('transcript_high_watermark', sa.Integer(), nullable=False),
        sa.Column('material_revisions', JSONB(), nullable=False), sa.Column('frozen_blocks', JSONB(), nullable=False),
        sa.Column('coverage', JSONB(), nullable=False), sa.Column('diagnostics', JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_context_snapshots_session_id', 'context_snapshots', ['session_id'])

def downgrade(): op.drop_table('context_snapshots')
