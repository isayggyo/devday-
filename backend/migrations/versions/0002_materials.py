"""Object-storage material documents and structured pages."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_materials"
down_revision = "0001_sessions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("material_documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("lecture_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(240), nullable=False),
        sa.Column("file_type", sa.String(10), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("processing_status", sa.String(30), nullable=False),
        sa.Column("original_ref", sa.String(500), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("error_code", sa.String(60)),
    )
    op.create_index("ix_material_documents_session_id", "material_documents", ["session_id"])
    op.create_table("material_pages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("material_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("image_ref", sa.String(500), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("document_id", "page_number", name="material_page_number"),
    )
    op.create_index("ix_material_pages_document_id", "material_pages", ["document_id"])


def downgrade():
    op.drop_table("material_pages")
    op.drop_table("material_documents")
