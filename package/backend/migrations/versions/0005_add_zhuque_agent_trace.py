"""add zhuque agent trace

Revision ID: 0005_add_zhuque_agent_trace
Revises: 0004_add_announcements
Create Date: 2026-06-04 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_add_zhuque_agent_trace"
down_revision = "0004_add_announcements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("optimization_sessions", sa.Column("zhuque_agent_trace", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("optimization_sessions", "zhuque_agent_trace")
