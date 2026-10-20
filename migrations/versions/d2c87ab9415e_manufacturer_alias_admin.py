"""Add audited administrator management for shared manufacturer aliases.

Revision ID: d2c87ab9415e
Revises: 6ec8a2f145bd
"""

from alembic import op
import sqlalchemy as sa


revision = "d2c87ab9415e"
down_revision = "6ec8a2f145bd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    conflict = bind.execute(sa.text("""
        WITH labels AS (
            SELECT o.id AS manufacturer_id,
                   lower(regexp_replace(btrim(o.name), '[[:space:]]+', ' ', 'g')) AS label
            FROM organizations o
            JOIN manufacturer_profiles mp ON mp.organization_id = o.id
            UNION ALL
            SELECT a.organization_id,
                   lower(regexp_replace(btrim(a.alias), '[[:space:]]+', ' ', 'g')) AS label
            FROM organization_aliases a
            JOIN manufacturer_profiles mp ON mp.organization_id = a.organization_id
        )
        SELECT label FROM labels GROUP BY label HAVING count(*) > 1 LIMIT 1
    """)).first()
    if conflict:
        raise RuntimeError(
            "Manufacturer alias migration found a normalized canonical-name or alias conflict; "
            "review shared reference data before retrying."
        )

    op.create_index(
        "uq_organization_aliases_normalized_alias",
        "organization_aliases",
        [sa.text("lower(trim(alias))")],
        unique=True,
    )
    op.create_table(
        "manufacturer_alias_audit_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("manufacturer_id", sa.UUID(), nullable=False),
        sa.Column("alias_id", sa.UUID(), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("previous_alias", sa.String(length=255), nullable=True),
        sa.Column("new_alias", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "action IN ('created', 'updated', 'deleted')",
            name="ck_manufacturer_alias_audit_action",
        ),
        sa.CheckConstraint(
            "(action = 'created' AND previous_alias IS NULL AND new_alias IS NOT NULL) "
            "OR (action = 'updated' AND previous_alias IS NOT NULL AND new_alias IS NOT NULL) "
            "OR (action = 'deleted' AND previous_alias IS NOT NULL AND new_alias IS NULL)",
            name="ck_manufacturer_alias_audit_values",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], ondelete="RESTRICT",
            name="fk_manufacturer_alias_audit_actor",
        ),
        sa.ForeignKeyConstraint(
            ["manufacturer_id"], ["organizations.id"], ondelete="RESTRICT",
            name="fk_manufacturer_alias_audit_manufacturer",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_manufacturer_alias_audit_events"),
    )
    op.create_index(
        "ix_manufacturer_alias_audit_manufacturer_created",
        "manufacturer_alias_audit_events",
        ["manufacturer_id", "created_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    has_history = bind.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM manufacturer_alias_audit_events)"
    )).scalar()
    if has_history:
        raise RuntimeError(
            "Cannot downgrade manufacturer alias management while alias audit history exists."
        )
    op.drop_index(
        "ix_manufacturer_alias_audit_manufacturer_created",
        table_name="manufacturer_alias_audit_events",
    )
    op.drop_table("manufacturer_alias_audit_events")
    op.drop_index(
        "uq_organization_aliases_normalized_alias",
        table_name="organization_aliases",
    )
