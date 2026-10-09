from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0009_personalized_final'
down_revision = '0008_visuals'
branch_labels = depends_on = None

def upgrade():
    op.add_column('lecture_sessions', sa.Column('course_key', sa.String(100)))
    op.add_column('lecture_sessions', sa.Column('final_result', JSONB()))
    op.create_index('ix_lecture_sessions_course_key', 'lecture_sessions', ['course_key'])
    op.add_column('student_questions', sa.Column('reactions', JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))

def downgrade():
    op.drop_column('student_questions', 'reactions')
    op.drop_index('ix_lecture_sessions_course_key', table_name='lecture_sessions')
    op.drop_column('lecture_sessions', 'final_result')
    op.drop_column('lecture_sessions', 'course_key')
