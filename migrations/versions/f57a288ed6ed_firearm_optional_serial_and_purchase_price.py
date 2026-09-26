"""Make firearm serial numbers optional and add purchase price.

Revision ID: f57a288ed6ed
Revises: ba5b6e5573c8
"""
from alembic import op
import sqlalchemy as sa


revision: str = "f57a288ed6ed"
down_revision: str = "ba5b6e5573c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "firearms", "serial_number",
        existing_type=sa.String(length=255), nullable=True,
    )
    op.add_column(
        "firearms",
        sa.Column("purchase_price", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "firearms",
        sa.Column("purchase_currency", sa.String(length=3), nullable=True),
    )
    op.create_check_constraint(
        "ck_firearms_purchase_price_nonnegative",
        "firearms",
        "purchase_price IS NULL OR purchase_price >= 0",
    )
    op.create_check_constraint(
        "ck_firearms_purchase_price_currency",
        "firearms",
        "(purchase_price IS NULL AND purchase_currency IS NULL) OR "
        "(purchase_price IS NOT NULL AND purchase_currency IS NOT NULL "
        "AND purchase_currency ~ '^[A-Z]{3}$')",
    )


def downgrade() -> None:
    # PostgreSQL rejects this if NULL serial numbers remain. Check before
    # removing price data; never invent serial numbers or delete firearms.
    op.alter_column(
        "firearms", "serial_number",
        existing_type=sa.String(length=255), nullable=False,
    )
    op.drop_constraint(
        "ck_firearms_purchase_price_currency", "firearms", type_="check",
    )
    op.drop_constraint(
        "ck_firearms_purchase_price_nonnegative", "firearms", type_="check",
    )
    # Downgrade permanently removes recorded purchase amounts and currencies.
    op.drop_column("firearms", "purchase_currency")
    op.drop_column("firearms", "purchase_price")
