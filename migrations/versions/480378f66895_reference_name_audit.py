"""Add administrator audit history for canonical reference renames.

Revision ID: 480378f66895
Revises: e8a1f3c0d64b
"""

from alembic import op
import sqlalchemy as sa


revision = "480378f66895"
down_revision = "e8a1f3c0d64b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reference_name_audit_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("reference_type", sa.String(length=16), nullable=False),
        sa.Column("reference_id", sa.UUID(), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=False),
        sa.Column("previous_name", sa.String(length=255), nullable=False),
        sa.Column("new_name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.CheckConstraint(
            "reference_type IN ('manufacturer', 'caliber')",
            name="ck_reference_name_audit_type",
        ),
        sa.CheckConstraint(
            "previous_name <> new_name",
            name="ck_reference_name_audit_changed",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], ondelete="RESTRICT",
            name="fk_reference_name_audit_actor",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reference_name_audit_events"),
    )
    op.create_index(
        "ix_reference_name_audit_reference_created",
        "reference_name_audit_events",
        ["reference_type", "reference_id", "created_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    has_history = bind.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM reference_name_audit_events)"
    )).scalar()
    if has_history:
        raise RuntimeError(
            "Cannot downgrade canonical reference renames while rename audit history exists."
        )
    op.drop_index(
        "ix_reference_name_audit_reference_created",
        table_name="reference_name_audit_events",
    )
    op.drop_table("reference_name_audit_events")
