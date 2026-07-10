"""add durable task events and worker leases

Revision ID: 0010_task_events_worker_leases
Revises: 0009_align_runtime_schema
Create Date: 2026-07-10 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_task_events_worker_leases"
down_revision = "0009_align_runtime_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "optimization_sessions",
        sa.Column("worker_attempt_count", sa.Integer(), nullable=True),
    )
    op.execute(
        "UPDATE optimization_sessions "
        "SET worker_attempt_count = 0 WHERE worker_attempt_count IS NULL"
    )

    op.create_table(
        "task_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("event_key", sa.String(length=160), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["optimization_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_task_events_created_at",
        "task_events",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_task_events_session_event_key",
        "task_events",
        ["session_id", "event_key"],
        unique=False,
    )
    op.create_index(
        "ix_task_events_session_id_id",
        "task_events",
        ["session_id", "id"],
        unique=False,
    )

    op.create_table(
        "worker_leases",
        sa.Column("worker_id", sa.String(length=128), nullable=False),
        sa.Column("boot_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("current_session_id", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["current_session_id"],
            ["optimization_sessions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("worker_id"),
    )
    op.create_index(
        "ix_worker_leases_current_session_id",
        "worker_leases",
        ["current_session_id"],
        unique=False,
    )
    op.create_index(
        "ix_worker_leases_last_seen_at",
        "worker_leases",
        ["last_seen_at"],
        unique=False,
    )
    op.create_index(
        "ix_worker_leases_state",
        "worker_leases",
        ["state"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_worker_leases_state", table_name="worker_leases")
    op.drop_index("ix_worker_leases_last_seen_at", table_name="worker_leases")
    op.drop_index("ix_worker_leases_current_session_id", table_name="worker_leases")
    op.drop_table("worker_leases")

    op.drop_index("ix_task_events_session_id_id", table_name="task_events")
    op.drop_index("ix_task_events_session_event_key", table_name="task_events")
    op.drop_index("ix_task_events_created_at", table_name="task_events")
    op.drop_table("task_events")
    op.drop_column("optimization_sessions", "worker_attempt_count")
