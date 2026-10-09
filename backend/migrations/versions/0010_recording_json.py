from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0010_recording_json'
down_revision = '0009_personalized_final'
branch_labels = depends_on = None


def upgrade():
    op.add_column('lecture_sessions', sa.Column('recording_input', JSONB()))


def downgrade():
    op.drop_column('lecture_sessions', 'recording_input')
