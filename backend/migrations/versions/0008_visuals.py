from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0008_visuals'
down_revision = '0007_questions'
branch_labels = depends_on = None

def upgrade():
    op.create_table('visual_explanations', sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('answer_id', sa.Uuid(), sa.ForeignKey('generated_answers.id', ondelete='CASCADE'), unique=True, nullable=False),
        sa.Column('layout_type', sa.String(30)), sa.Column('requested_layout', sa.String(30)),
        sa.Column('title', sa.Text(), nullable=False), sa.Column('elements', JSONB(), nullable=False),
        sa.Column('source_refs', JSONB(), nullable=False), sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False), sa.Column('error_code', sa.String(80)),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))

def downgrade(): op.drop_table('visual_explanations')
