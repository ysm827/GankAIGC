"""add browser agent zhuque jobs

Revision ID: 0008_browser_agent_zhuque_jobs
Revises: 0007_doc_structure_meta
Create Date: 2026-07-06 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_browser_agent_zhuque_jobs"
down_revision = "0007_doc_structure_meta"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "browser_agent_pairings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("pairing_code_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("claimed_by_agent_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pairing_code_hash"),
    )
    op.create_index(op.f("ix_browser_agent_pairings_id"), "browser_agent_pairings", ["id"], unique=False)
    op.create_index(op.f("ix_browser_agent_pairings_user_id"), "browser_agent_pairings", ["user_id"], unique=False)
    op.create_index(op.f("ix_browser_agent_pairings_pairing_code_hash"), "browser_agent_pairings", ["pairing_code_hash"], unique=False)
    op.create_index(op.f("ix_browser_agent_pairings_expires_at"), "browser_agent_pairings", ["expires_at"], unique=False)
    op.create_index(op.f("ix_browser_agent_pairings_created_at"), "browser_agent_pairings", ["created_at"], unique=False)

    op.create_table(
        "browser_agents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("capabilities_json", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("extension_version", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id"),
    )
    op.create_index(op.f("ix_browser_agents_id"), "browser_agents", ["id"], unique=False)
    op.create_index(op.f("ix_browser_agents_user_id"), "browser_agents", ["user_id"], unique=False)
    op.create_index(op.f("ix_browser_agents_agent_id"), "browser_agents", ["agent_id"], unique=False)
    op.create_index(op.f("ix_browser_agents_status"), "browser_agents", ["status"], unique=False)
    op.create_index(op.f("ix_browser_agents_last_seen_at"), "browser_agents", ["last_seen_at"], unique=False)
    op.create_index(op.f("ix_browser_agents_created_at"), "browser_agents", ["created_at"], unique=False)
    op.create_index(op.f("ix_browser_agents_revoked_at"), "browser_agents", ["revoked_at"], unique=False)

    op.create_table(
        "zhuque_agent_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("segment_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload_text", sa.Text(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("progress_json", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("claimed_by_agent_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["claimed_by_agent_id"], ["browser_agents.agent_id"]),
        sa.ForeignKeyConstraint(["segment_id"], ["optimization_segments.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["optimization_sessions.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
    )
    op.create_index(op.f("ix_zhuque_agent_jobs_id"), "zhuque_agent_jobs", ["id"], unique=False)
    op.create_index(op.f("ix_zhuque_agent_jobs_job_id"), "zhuque_agent_jobs", ["job_id"], unique=False)
    op.create_index(op.f("ix_zhuque_agent_jobs_user_id"), "zhuque_agent_jobs", ["user_id"], unique=False)
    op.create_index(op.f("ix_zhuque_agent_jobs_session_id"), "zhuque_agent_jobs", ["session_id"], unique=False)
    op.create_index(op.f("ix_zhuque_agent_jobs_segment_id"), "zhuque_agent_jobs", ["segment_id"], unique=False)
    op.create_index(op.f("ix_zhuque_agent_jobs_status"), "zhuque_agent_jobs", ["status"], unique=False)
    op.create_index(op.f("ix_zhuque_agent_jobs_payload_hash"), "zhuque_agent_jobs", ["payload_hash"], unique=False)
    op.create_index(op.f("ix_zhuque_agent_jobs_error_code"), "zhuque_agent_jobs", ["error_code"], unique=False)
    op.create_index(op.f("ix_zhuque_agent_jobs_claimed_by_agent_id"), "zhuque_agent_jobs", ["claimed_by_agent_id"], unique=False)
    op.create_index(op.f("ix_zhuque_agent_jobs_created_at"), "zhuque_agent_jobs", ["created_at"], unique=False)
    op.create_index(op.f("ix_zhuque_agent_jobs_expires_at"), "zhuque_agent_jobs", ["expires_at"], unique=False)
    op.create_index(op.f("ix_zhuque_agent_jobs_heartbeat_at"), "zhuque_agent_jobs", ["heartbeat_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_zhuque_agent_jobs_heartbeat_at"), table_name="zhuque_agent_jobs")
    op.drop_index(op.f("ix_zhuque_agent_jobs_expires_at"), table_name="zhuque_agent_jobs")
    op.drop_index(op.f("ix_zhuque_agent_jobs_created_at"), table_name="zhuque_agent_jobs")
    op.drop_index(op.f("ix_zhuque_agent_jobs_claimed_by_agent_id"), table_name="zhuque_agent_jobs")
    op.drop_index(op.f("ix_zhuque_agent_jobs_error_code"), table_name="zhuque_agent_jobs")
    op.drop_index(op.f("ix_zhuque_agent_jobs_payload_hash"), table_name="zhuque_agent_jobs")
    op.drop_index(op.f("ix_zhuque_agent_jobs_status"), table_name="zhuque_agent_jobs")
    op.drop_index(op.f("ix_zhuque_agent_jobs_segment_id"), table_name="zhuque_agent_jobs")
    op.drop_index(op.f("ix_zhuque_agent_jobs_session_id"), table_name="zhuque_agent_jobs")
    op.drop_index(op.f("ix_zhuque_agent_jobs_user_id"), table_name="zhuque_agent_jobs")
    op.drop_index(op.f("ix_zhuque_agent_jobs_job_id"), table_name="zhuque_agent_jobs")
    op.drop_index(op.f("ix_zhuque_agent_jobs_id"), table_name="zhuque_agent_jobs")
    op.drop_table("zhuque_agent_jobs")

    op.drop_index(op.f("ix_browser_agents_revoked_at"), table_name="browser_agents")
    op.drop_index(op.f("ix_browser_agents_created_at"), table_name="browser_agents")
    op.drop_index(op.f("ix_browser_agents_last_seen_at"), table_name="browser_agents")
    op.drop_index(op.f("ix_browser_agents_status"), table_name="browser_agents")
    op.drop_index(op.f("ix_browser_agents_agent_id"), table_name="browser_agents")
    op.drop_index(op.f("ix_browser_agents_user_id"), table_name="browser_agents")
    op.drop_index(op.f("ix_browser_agents_id"), table_name="browser_agents")
    op.drop_table("browser_agents")

    op.drop_index(op.f("ix_browser_agent_pairings_created_at"), table_name="browser_agent_pairings")
    op.drop_index(op.f("ix_browser_agent_pairings_expires_at"), table_name="browser_agent_pairings")
    op.drop_index(op.f("ix_browser_agent_pairings_pairing_code_hash"), table_name="browser_agent_pairings")
    op.drop_index(op.f("ix_browser_agent_pairings_user_id"), table_name="browser_agent_pairings")
    op.drop_index(op.f("ix_browser_agent_pairings_id"), table_name="browser_agent_pairings")
    op.drop_table("browser_agent_pairings")
