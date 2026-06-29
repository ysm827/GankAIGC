"""add document structure metadata

Revision ID: 0007_doc_structure_meta
Revises: 0006_add_zhuque_prompt_memories
Create Date: 2026-06-29 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_doc_structure_meta"
down_revision = "0006_add_zhuque_prompt_memories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("optimization_sessions", sa.Column("document_format", sa.String(length=32), nullable=True))
    op.add_column("optimization_sessions", sa.Column("parse_engine", sa.String(length=64), nullable=True))
    op.add_column("optimization_sessions", sa.Column("parse_fallback_used", sa.Boolean(), nullable=True))
    op.add_column("optimization_sessions", sa.Column("parse_trace", sa.Text(), nullable=True))

    op.add_column("optimization_segments", sa.Column("semantic_type", sa.String(length=64), nullable=True))
    op.add_column("optimization_segments", sa.Column("semantic_source", sa.String(length=64), nullable=True))
    op.add_column("optimization_segments", sa.Column("semantic_confidence", sa.Float(), nullable=True))
    op.add_column("optimization_segments", sa.Column("reduce_allowed", sa.Boolean(), nullable=True))
    op.add_column("optimization_segments", sa.Column("semantic_reason", sa.String(length=128), nullable=True))
    op.add_column("optimization_segments", sa.Column("char_start", sa.Integer(), nullable=True))
    op.add_column("optimization_segments", sa.Column("char_end", sa.Integer(), nullable=True))
    op.add_column("optimization_segments", sa.Column("page_number", sa.Integer(), nullable=True))
    op.add_column("optimization_segments", sa.Column("bbox_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("optimization_segments", "bbox_json")
    op.drop_column("optimization_segments", "page_number")
    op.drop_column("optimization_segments", "char_end")
    op.drop_column("optimization_segments", "char_start")
    op.drop_column("optimization_segments", "semantic_reason")
    op.drop_column("optimization_segments", "reduce_allowed")
    op.drop_column("optimization_segments", "semantic_confidence")
    op.drop_column("optimization_segments", "semantic_source")
    op.drop_column("optimization_segments", "semantic_type")

    op.drop_column("optimization_sessions", "parse_trace")
    op.drop_column("optimization_sessions", "parse_fallback_used")
    op.drop_column("optimization_sessions", "parse_engine")
    op.drop_column("optimization_sessions", "document_format")
