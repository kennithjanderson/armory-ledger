"""Add directional inventory sharing invitations and section grants.

Revision ID: 12ef7a4b9c31
Revises: 480378f66895
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "12ef7a4b9c31"
down_revision = "480378f66895"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_shares",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("recipient_id", sa.UUID(), nullable=True),
        sa.Column("invite_email", sa.String(length=320), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("firearms_access", sa.String(length=5), server_default="none", nullable=False),
        sa.Column("ammunition_access", sa.String(length=5), server_default="none", nullable=False),
        sa.Column("accessories_access", sa.String(length=5), server_default="none", nullable=False),
        sa.Column("shooting_log_access", sa.String(length=5), server_default="none", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("owner_id <> recipient_id OR recipient_id IS NULL", name="ck_inventory_shares_not_self"),
        sa.CheckConstraint("status IN ('pending', 'accepted', 'declined', 'revoked')", name="ck_inventory_shares_status"),
        sa.CheckConstraint("firearms_access IN ('none', 'ro', 'rw')", name="ck_inventory_shares_firearms_access"),
        sa.CheckConstraint("ammunition_access IN ('none', 'ro', 'rw')", name="ck_inventory_shares_ammunition_access"),
        sa.CheckConstraint("accessories_access IN ('none', 'ro', 'rw')", name="ck_inventory_shares_accessories_access"),
        sa.CheckConstraint("shooting_log_access IN ('none', 'ro', 'rw')", name="ck_inventory_shares_shooting_log_access"),
        sa.CheckConstraint(
            "firearms_access <> 'none' OR ammunition_access <> 'none' OR "
            "accessories_access <> 'none' OR shooting_log_access <> 'none'",
            name="ck_inventory_shares_has_access",
        ),
        sa.CheckConstraint(
            "status <> 'accepted' OR (recipient_id IS NOT NULL AND accepted_at IS NOT NULL)",
            name="ck_inventory_shares_accepted_has_recipient",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE", name="fk_inventory_shares_owner"),
        sa.ForeignKeyConstraint(["recipient_id"], ["users.id"], ondelete="CASCADE", name="fk_inventory_shares_recipient"),
        sa.PrimaryKeyConstraint("id", name="pk_inventory_shares"),
        sa.UniqueConstraint("owner_id", "recipient_id", name="uq_inventory_shares_owner_recipient"),
    )
    op.create_index("ix_inventory_shares_owner_status", "inventory_shares", ["owner_id", "status"])
    op.create_index("ix_inventory_shares_recipient_status", "inventory_shares", ["recipient_id", "status"])
    op.create_index(
        "uq_inventory_shares_owner_active_email", "inventory_shares",
        ["owner_id", sa.text("lower(trim(invite_email))")], unique=True,
        postgresql_where=sa.text("status IN ('pending', 'accepted')"),
    )
    op.create_table(
        "inventory_share_audit_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("share_id", sa.UUID(), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=False),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("changes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "action IN ('invited', 'reinvited', 'claimed', 'permissions_changed', 'accepted', 'declined', 'revoked')",
            name="ck_inventory_share_audit_action",
        ),
        sa.ForeignKeyConstraint(["share_id"], ["inventory_shares.id"], ondelete="CASCADE", name="fk_inventory_share_audit_share"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT", name="fk_inventory_share_audit_actor"),
        sa.PrimaryKeyConstraint("id", name="pk_inventory_share_audit_events"),
    )
    op.create_index(
        "ix_inventory_share_audit_share_created",
        "inventory_share_audit_events", ["share_id", "created_at"],
    )
    op.add_column("notification_recipients", sa.Column("email_override", sa.String(length=320), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    has_shares = bind.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM inventory_shares)"
    )).scalar()
    has_overrides = bind.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM notification_recipients WHERE email_override IS NOT NULL)"
    )).scalar()
    if has_shares or has_overrides:
        raise RuntimeError(
            "Cannot downgrade inventory sharing while invitations or external invitation deliveries exist."
        )
    op.drop_column("notification_recipients", "email_override")
    op.drop_index("ix_inventory_share_audit_share_created", table_name="inventory_share_audit_events")
    op.drop_table("inventory_share_audit_events")
    op.drop_index("uq_inventory_shares_owner_active_email", table_name="inventory_shares")
    op.drop_index("ix_inventory_shares_recipient_status", table_name="inventory_shares")
    op.drop_index("ix_inventory_shares_owner_status", table_name="inventory_shares")
    op.drop_table("inventory_shares")
