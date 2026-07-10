"""align Alembic schema with the runtime models

Revision ID: 0009_align_runtime_schema
Revises: 0008_browser_agent_zhuque_jobs
Create Date: 2026-07-10 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_align_runtime_schema"
down_revision = "0008_browser_agent_zhuque_jobs"
branch_labels = None
depends_on = None


def _replace_constraint_with_unique_index(
    table_name: str,
    column_name: str,
    constraint_name: str,
    index_name: str,
) -> None:
    # Keep the unique constraint in place while replacing the non-unique index,
    # then remove the redundant constraint after the unique index is ready.
    op.drop_index(index_name, table_name=table_name)
    op.create_index(index_name, table_name, [column_name], unique=True)
    op.drop_constraint(constraint_name, table_name, type_="unique")


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_url", sa.String(length=512), nullable=True))
    op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("zhuque_free_uses_remaining", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("zhuque_total_uses", sa.Integer(), nullable=True))

    op.add_column(
        "user_provider_configs",
        sa.Column(
            "api_format",
            sa.String(length=40),
            nullable=False,
            server_default="openai_chat",
        ),
    )
    op.alter_column("user_provider_configs", "api_format", server_default=None)

    for column_name in (
        "polish_api_format",
        "enhance_api_format",
        "emotion_api_format",
    ):
        op.add_column(
            "optimization_sessions",
            sa.Column(column_name, sa.String(length=40), nullable=True),
        )

    op.add_column("optimization_segments", sa.Column("zhuque_detect_rate", sa.Float(), nullable=True))
    op.add_column("optimization_segments", sa.Column("zhuque_detect_result", sa.Text(), nullable=True))
    op.add_column("optimization_segments", sa.Column("zhuque_detect_count", sa.Integer(), nullable=True))
    op.add_column("optimization_segments", sa.Column("zhuque_reduce_attempt", sa.Integer(), nullable=True))
    op.add_column("optimization_segments", sa.Column("zhuque_reduced_text", sa.Text(), nullable=True))

    _replace_constraint_with_unique_index(
        "browser_agent_pairings",
        "pairing_code_hash",
        "browser_agent_pairings_pairing_code_hash_key",
        "ix_browser_agent_pairings_pairing_code_hash",
    )
    op.drop_constraint(
        "zhuque_agent_jobs_claimed_by_agent_id_fkey",
        "zhuque_agent_jobs",
        type_="foreignkey",
    )
    _replace_constraint_with_unique_index(
        "browser_agents",
        "agent_id",
        "browser_agents_agent_id_key",
        "ix_browser_agents_agent_id",
    )
    op.create_foreign_key(
        "zhuque_agent_jobs_claimed_by_agent_id_fkey",
        "zhuque_agent_jobs",
        "browser_agents",
        ["claimed_by_agent_id"],
        ["agent_id"],
    )
    _replace_constraint_with_unique_index(
        "zhuque_agent_jobs",
        "job_id",
        "zhuque_agent_jobs_job_id_key",
        "ix_zhuque_agent_jobs_job_id",
    )

    op.drop_index("idx_zhuque_prompt_memories_signature_hash", table_name="zhuque_prompt_memories")
    op.drop_index("idx_zhuque_prompt_memories_enabled", table_name="zhuque_prompt_memories")
    op.create_index(
        op.f("ix_zhuque_prompt_memories_signature_hash"),
        "zhuque_prompt_memories",
        ["signature_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_zhuque_prompt_memories_source"),
        "zhuque_prompt_memories",
        ["source"],
        unique=False,
    )
    op.create_index(
        op.f("ix_zhuque_prompt_memories_enabled"),
        "zhuque_prompt_memories",
        ["enabled"],
        unique=False,
    )
    op.create_index(
        op.f("ix_zhuque_prompt_memories_created_at"),
        "zhuque_prompt_memories",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_zhuque_prompt_memories_created_at"), table_name="zhuque_prompt_memories")
    op.drop_index(op.f("ix_zhuque_prompt_memories_enabled"), table_name="zhuque_prompt_memories")
    op.drop_index(op.f("ix_zhuque_prompt_memories_source"), table_name="zhuque_prompt_memories")
    op.drop_index(op.f("ix_zhuque_prompt_memories_signature_hash"), table_name="zhuque_prompt_memories")
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

    op.drop_constraint(
        "zhuque_agent_jobs_claimed_by_agent_id_fkey",
        "zhuque_agent_jobs",
        type_="foreignkey",
    )
    for table_name, column_name, constraint_name, index_name in (
        (
            "zhuque_agent_jobs",
            "job_id",
            "zhuque_agent_jobs_job_id_key",
            "ix_zhuque_agent_jobs_job_id",
        ),
        (
            "browser_agents",
            "agent_id",
            "browser_agents_agent_id_key",
            "ix_browser_agents_agent_id",
        ),
        (
            "browser_agent_pairings",
            "pairing_code_hash",
            "browser_agent_pairings_pairing_code_hash_key",
            "ix_browser_agent_pairings_pairing_code_hash",
        ),
    ):
        op.create_unique_constraint(constraint_name, table_name, [column_name])
        op.drop_index(index_name, table_name=table_name)
        op.create_index(index_name, table_name, [column_name], unique=False)
    op.create_foreign_key(
        "zhuque_agent_jobs_claimed_by_agent_id_fkey",
        "zhuque_agent_jobs",
        "browser_agents",
        ["claimed_by_agent_id"],
        ["agent_id"],
    )

    op.drop_column("optimization_segments", "zhuque_reduced_text")
    op.drop_column("optimization_segments", "zhuque_reduce_attempt")
    op.drop_column("optimization_segments", "zhuque_detect_count")
    op.drop_column("optimization_segments", "zhuque_detect_result")
    op.drop_column("optimization_segments", "zhuque_detect_rate")

    op.drop_column("optimization_sessions", "emotion_api_format")
    op.drop_column("optimization_sessions", "enhance_api_format")
    op.drop_column("optimization_sessions", "polish_api_format")

    op.drop_column("user_provider_configs", "api_format")
    op.drop_column("users", "zhuque_total_uses")
    op.drop_column("users", "zhuque_free_uses_remaining")
    op.drop_column("users", "token_version")
    op.drop_column("users", "avatar_url")
