"""add zhuque prompt memories

Revision ID: 0006_add_zhuque_prompt_memories
Revises: 0005_add_zhuque_agent_trace
Create Date: 2026-06-04 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_add_zhuque_prompt_memories"
down_revision = "0005_add_zhuque_agent_trace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "zhuque_prompt_memories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("signature_hash", sa.String(length=64), nullable=False),
        sa.Column("failure_signature", sa.Text(), nullable=False),
        sa.Column("prompt_patch", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("before_rate", sa.Float(), nullable=True),
        sa.Column("after_rate", sa.Float(), nullable=True),
        sa.Column("rate_delta", sa.Float(), nullable=True),
        sa.Column("uses", sa.Integer(), nullable=True),
        sa.Column("successes", sa.Integer(), nullable=True),
        sa.Column("failures", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_zhuque_prompt_memories_id"), "zhuque_prompt_memories", ["id"], unique=False)
    op.create_index(
        "idx_zhuque_prompt_memories_signature_hash",
        "zhuque_prompt_memories",
        ["signature_hash"],
        unique=False,
    )
    op.create_index(
        "idx_zhuque_prompt_memories_enabled",
        "zhuque_prompt_memories",
        ["enabled"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_zhuque_prompt_memories_enabled", table_name="zhuque_prompt_memories")
    op.drop_index("idx_zhuque_prompt_memories_signature_hash", table_name="zhuque_prompt_memories")
    op.drop_index(op.f("ix_zhuque_prompt_memories_id"), table_name="zhuque_prompt_memories")
    op.drop_table("zhuque_prompt_memories")
