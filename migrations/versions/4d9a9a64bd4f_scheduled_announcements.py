"""Add scheduled server announcements.

Revision ID: 4d9a9a64bd4f
Revises: f57a288ed6ed
"""
from alembic import op
import sqlalchemy as sa


revision: str = "4d9a9a64bd4f"
down_revision: str = "f57a288ed6ed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "announcements",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=False),
        sa.Column("updated_by_user_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.CheckConstraint(
            "ends_at > starts_at", name="ck_announcements_time_window",
        ),
        sa.CheckConstraint(
            "severity IN ('info', 'success', 'warning', 'danger')",
            name="ck_announcements_severity",
        ),
        sa.CheckConstraint(
            "length(trim(title)) > 0", name="ck_announcements_title",
        ),
        sa.CheckConstraint(
            "length(trim(message)) > 0 AND length(message) <= 5000",
            name="ck_announcements_message",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_announcements_starts_at"), "announcements", ["starts_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_announcements_ends_at"), "announcements", ["ends_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_announcements_ends_at"), table_name="announcements")
    op.drop_index(op.f("ix_announcements_starts_at"), table_name="announcements")
    op.drop_table("announcements")
