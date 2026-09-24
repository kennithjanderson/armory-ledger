"""update firearm dates and status

Revision ID: 5c0a11b43be4
Revises: 3ca46faf814f
Create Date: 2026-09-24 01:17:40.377686

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "5c0a11b43be4"
down_revision: Union[str, Sequence[str], None] = "3ca46faf814f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # ---------------------------------------------------------
    # Firearm status
    # ---------------------------------------------------------
    #
    # PostgreSQL enum values must be added explicitly. Alembic
    # autogenerate does not detect additions to an existing enum.
    #
    op.execute(
        "ALTER TYPE firearm_status "
        "ADD VALUE IF NOT EXISTS 'decommissioned'"
    )

    # ---------------------------------------------------------
    # Shared firearm date precision enum
    # ---------------------------------------------------------
    firearm_date_precision = postgresql.ENUM(
        "exact",
        "month",
        "year",
        "approximate_year",
        "unknown",
        name="firearm_date_precision",
        create_type=False,
    )

    firearm_date_precision.create(bind, checkfirst=True)

    # ---------------------------------------------------------
    # New date columns
    # ---------------------------------------------------------
    op.add_column(
        "firearms",
        sa.Column(
            "manufacture_date",
            sa.Date(),
            nullable=True,
        ),
    )

    op.add_column(
        "firearms",
        sa.Column(
            "manufacture_date_precision",
            firearm_date_precision,
            nullable=False,
            server_default="unknown",
        ),
    )

    op.add_column(
        "firearms",
        sa.Column(
            "obtained_date",
            sa.Date(),
            nullable=True,
        ),
    )

    op.add_column(
        "firearms",
        sa.Column(
            "obtained_date_precision",
            firearm_date_precision,
            nullable=False,
            server_default="unknown",
        ),
    )

    # ---------------------------------------------------------
    # Preserve existing manufacture-date information
    # ---------------------------------------------------------
    #
    # Existing exact dates remain exact.
    # Existing year-only dates remain year precision.
    # Existing estimated dates become approximate-year precision.
    #
    op.execute(
        """
        UPDATE firearms
        SET
            manufacture_date = manufacture_date_from,
            manufacture_date_precision =
                CASE manufacture_date_confidence::text
                    WHEN 'exact' THEN 'exact'::firearm_date_precision
                    WHEN 'year' THEN 'year'::firearm_date_precision
                    WHEN 'estimated' THEN 'approximate_year'::firearm_date_precision
                    ELSE 'unknown'::firearm_date_precision
                END
        WHERE manufacture_date_from IS NOT NULL
        """
    )

    # Application defaults should own new records after migration.
    op.alter_column(
        "firearms",
        "manufacture_date_precision",
        server_default=None,
    )

    op.alter_column(
        "firearms",
        "obtained_date_precision",
        server_default=None,
    )

    # ---------------------------------------------------------
    # Remove superseded manufacture-date fields
    # ---------------------------------------------------------
    op.drop_column(
        "firearms",
        "manufacture_date_confidence",
    )

    op.drop_column(
        "firearms",
        "manufacture_date_from",
    )

    op.drop_column(
        "firearms",
        "manufacture_date_to",
    )


def downgrade() -> None:
    bind = op.get_bind()

    manufacture_date_confidence = postgresql.ENUM(
        "exact",
        "year",
        "estimated",
        "unknown",
        name="manufacture_date_confidence",
        create_type=False,
    )

    manufacture_date_confidence.create(
        bind,
        checkfirst=True,
    )

    # ---------------------------------------------------------
    # Restore previous manufacture-date columns
    # ---------------------------------------------------------
    op.add_column(
        "firearms",
        sa.Column(
            "manufacture_date_from",
            sa.Date(),
            nullable=True,
        ),
    )

    op.add_column(
        "firearms",
        sa.Column(
            "manufacture_date_to",
            sa.Date(),
            nullable=True,
        ),
    )

    op.add_column(
        "firearms",
        sa.Column(
            "manufacture_date_confidence",
            manufacture_date_confidence,
            nullable=False,
            server_default="unknown",
        ),
    )

    # Preserve as much manufacture-date information as the old
    # schema can represent.
    op.execute(
        """
        UPDATE firearms
        SET
            manufacture_date_from = manufacture_date,
            manufacture_date_to = manufacture_date,
            manufacture_date_confidence =
                CASE manufacture_date_precision::text
                    WHEN 'exact' THEN 'exact'::manufacture_date_confidence
                    WHEN 'year' THEN 'year'::manufacture_date_confidence
                    WHEN 'month' THEN 'estimated'::manufacture_date_confidence
                    WHEN 'approximate_year' THEN 'estimated'::manufacture_date_confidence
                    ELSE 'unknown'::manufacture_date_confidence
                END
        WHERE manufacture_date IS NOT NULL
        """
    )

    op.alter_column(
        "firearms",
        "manufacture_date_confidence",
        server_default=None,
    )

    # ---------------------------------------------------------
    # Remove new date fields
    # ---------------------------------------------------------
    op.drop_column(
        "firearms",
        "obtained_date_precision",
    )

    op.drop_column(
        "firearms",
        "obtained_date",
    )

    op.drop_column(
        "firearms",
        "manufacture_date_precision",
    )

    op.drop_column(
        "firearms",
        "manufacture_date",
    )

    postgresql.ENUM(
        name="firearm_date_precision",
    ).drop(
        bind,
        checkfirst=True,
    )

    # PostgreSQL cannot simply remove an enum value from
    # firearm_status. Leave 'decommissioned' in the enum type on
    # downgrade; the old application code will simply never use it.