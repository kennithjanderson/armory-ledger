"""add accessory quantity

Revision ID: ba5b6e5573c8
Revises: 5c0a11b43be4
Create Date: 2026-09-24 19:23:42.815472

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ba5b6e5573c8'
down_revision: Union[str, Sequence[str], None] = '5c0a11b43be4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "accessories",
        sa.Column(
            "quantity",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
    )

    op.create_check_constraint(
        "ck_accessories_quantity_positive",
        "accessories",
        "quantity >= 1",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_accessories_quantity_positive",
        "accessories",
        type_="check",
    )

    op.drop_column(
        "accessories",
        "quantity",
    )
