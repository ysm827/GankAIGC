"""add announcements

Revision ID: 0004_add_announcements
Revises: 0003_add_admin_audit_logs
Create Date: 2026-05-12 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_add_announcements"
down_revision = "0003_add_admin_audit_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "announcements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_announcements_category"), "announcements", ["category"], unique=False)
    op.create_index(op.f("ix_announcements_is_active"), "announcements", ["is_active"], unique=False)
    op.create_index(op.f("ix_announcements_created_at"), "announcements", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_announcements_created_at"), table_name="announcements")
    op.drop_index(op.f("ix_announcements_is_active"), table_name="announcements")
    op.drop_index(op.f("ix_announcements_category"), table_name="announcements")
    op.drop_table("announcements")
