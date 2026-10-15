"""Classify existing range sessions as shooting activities.

Revision ID: 82c1f947ad30
Revises: 4d9a9a64bd4f

Downgrade removes classification only; shooting and inventory records remain.
"""
from alembic import op
import sqlalchemy as sa


revision: str = "82c1f947ad30"
down_revision: str = "4d9a9a64bd4f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("range_sessions") as batch:
        batch.add_column(sa.Column(
            "activity_type", sa.String(length=20),
            server_default="range", nullable=False,
        ))
        batch.create_check_constraint(
            "ck_range_sessions_activity_type",
            "activity_type IN ('range', 'hunting', 'training', 'defensive', 'other')",
        )


def downgrade() -> None:
    with op.batch_alter_table("range_sessions") as batch:
        batch.drop_constraint("ck_range_sessions_activity_type", type_="check")
        batch.drop_column("activity_type")
