"""Add audited administrator management for shared caliber aliases.

Revision ID: e8a1f3c0d64b
Revises: d2c87ab9415e
"""

from alembic import op
import sqlalchemy as sa


revision = "e8a1f3c0d64b"
down_revision = "d2c87ab9415e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    conflict = bind.execute(sa.text("""
        WITH aliases AS (
            SELECT a.id, a.caliber_id,
                   lower(regexp_replace(btrim(a.alias), '[[:space:]]+', ' ', 'g')) AS label
            FROM caliber_aliases a
        ), names AS (
            SELECT c.id AS caliber_id,
                   lower(regexp_replace(btrim(c.name), '[[:space:]]+', ' ', 'g')) AS label
            FROM calibers c
        )
        SELECT candidate.label
        FROM aliases candidate
        WHERE EXISTS (
            SELECT 1 FROM aliases other
            WHERE other.id <> candidate.id AND other.label = candidate.label
        ) OR EXISTS (
            SELECT 1 FROM names
            WHERE names.label = candidate.label
        )
        LIMIT 1
    """)).first()
    if conflict:
        raise RuntimeError(
            "Caliber alias migration found a normalized alias conflict with another alias "
            "or canonical caliber; review shared reference data before retrying."
        )

    op.create_index(
        "uq_caliber_aliases_normalized_alias",
        "caliber_aliases",
        [sa.text("lower(trim(alias))")],
        unique=True,
    )
    op.create_table(
        "caliber_alias_audit_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("caliber_id", sa.UUID(), nullable=False),
        sa.Column("alias_id", sa.UUID(), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("previous_alias", sa.String(length=100), nullable=True),
        sa.Column("new_alias", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "action IN ('created', 'deleted')",
            name="ck_caliber_alias_audit_action",
        ),
        sa.CheckConstraint(
            "(action = 'created' AND previous_alias IS NULL AND new_alias IS NOT NULL) "
            "OR (action = 'deleted' AND previous_alias IS NOT NULL AND new_alias IS NULL)",
            name="ck_caliber_alias_audit_values",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], ondelete="RESTRICT",
            name="fk_caliber_alias_audit_actor",
        ),
        sa.ForeignKeyConstraint(
            ["caliber_id"], ["calibers.id"], ondelete="RESTRICT",
            name="fk_caliber_alias_audit_caliber",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_caliber_alias_audit_events"),
    )
    op.create_index(
        "ix_caliber_alias_audit_caliber_created",
        "caliber_alias_audit_events",
        ["caliber_id", "created_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    has_history = bind.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM caliber_alias_audit_events)"
    )).scalar()
    if has_history:
        raise RuntimeError(
            "Cannot downgrade caliber alias management while alias audit history exists."
        )
    op.drop_index(
        "ix_caliber_alias_audit_caliber_created",
        table_name="caliber_alias_audit_events",
    )
    op.drop_table("caliber_alias_audit_events")
    op.drop_index(
        "uq_caliber_aliases_normalized_alias",
        table_name="caliber_aliases",
    )
