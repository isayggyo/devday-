from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0007_questions'
down_revision = '0006_context'
branch_labels = depends_on = None

def upgrade():
    op.create_table('student_questions', sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('session_id', sa.Uuid(), sa.ForeignKey('lecture_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('client_question_id', sa.Uuid(), nullable=False), sa.Column('question_text', sa.Text(), nullable=False),
        sa.Column('context_snapshot_id', sa.Uuid(), sa.ForeignKey('context_snapshots.snapshot_id', ondelete='CASCADE'), nullable=False),
        sa.Column('selected_page_ids', JSONB(), nullable=False), sa.Column('status', sa.String(20), nullable=False),
        sa.Column('error_code', sa.String(80)), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('session_id', 'client_question_id', name='question_client_id'))
    op.create_index('ix_student_questions_session_id', 'student_questions', ['session_id'])
    op.create_table('generated_answers', sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('question_id', sa.Uuid(), sa.ForeignKey('student_questions.id', ondelete='CASCADE'), unique=True, nullable=False),
        sa.Column('answer', sa.Text(), nullable=False), sa.Column('citations', JSONB(), nullable=False),
        sa.Column('grounding_status', sa.String(30), nullable=False), sa.Column('needs_visual', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))

def downgrade():
    op.drop_table('generated_answers'); op.drop_table('student_questions')
