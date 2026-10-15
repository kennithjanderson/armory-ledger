"""Preserve lot identities while recording internal merge transfers.

Revision ID: c7d2a960e148
Revises: 82c1f947ad30

Downgrade refuses populated merge history. PostgreSQL enum labels remain on
downgrade; removing them would require replacing a shared enum type.
"""
from alembic import op
import sqlalchemy as sa

revision: str = "c7d2a960e148"
down_revision: str = "82c1f947ad30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        # No rows/defaults use these values until after migration commit.
        op.execute("ALTER TYPE ammo_transaction_type ADD VALUE IF NOT EXISTS 'merge_in'")
        op.execute("ALTER TYPE ammo_transaction_type ADD VALUE IF NOT EXISTS 'merge_out'")
    with op.batch_alter_table("ammo_lots") as batch:
        batch.add_column(sa.Column("merged_into_lot_id", sa.UUID(), nullable=True))
        batch.create_foreign_key("fk_ammo_lots_merged_into", "ammo_lots", ["merged_into_lot_id"], ["id"])
        batch.create_index("ix_ammo_lots_merged_into_lot_id", ["merged_into_lot_id"])
    op.create_table(
        "ammo_lot_merges",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("owner_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("source_lot_id", sa.UUID(), sa.ForeignKey("ammo_lots.id"), nullable=False, unique=True),
        sa.Column("destination_lot_id", sa.UUID(), sa.ForeignKey("ammo_lots.id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_ammo_lot_merges_quantity"),
        sa.CheckConstraint("source_lot_id <> destination_lot_id", name="ck_ammo_lot_merges_distinct"),
    )
    op.create_index("ix_ammo_lot_merges_owner_id", "ammo_lot_merges", ["owner_id"])
    op.create_index("ix_ammo_lot_merges_destination_lot_id", "ammo_lot_merges", ["destination_lot_id"])
    with op.batch_alter_table("ammo_inventory_transactions") as batch:
        batch.add_column(sa.Column("merge_id", sa.UUID(), nullable=True))
        batch.create_foreign_key("fk_ammo_inventory_transactions_merge", "ammo_lot_merges", ["merge_id"], ["id"])
        batch.create_index("ix_ammo_inventory_transactions_merge_id", ["merge_id"])


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT 1 FROM ammo_lot_merges LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade with merge history. An audited reversal design is required.")
    with op.batch_alter_table("ammo_inventory_transactions") as batch:
        batch.drop_index("ix_ammo_inventory_transactions_merge_id")
        batch.drop_constraint("fk_ammo_inventory_transactions_merge", type_="foreignkey")
        batch.drop_column("merge_id")
    op.drop_table("ammo_lot_merges")
    with op.batch_alter_table("ammo_lots") as batch:
        batch.drop_index("ix_ammo_lots_merged_into_lot_id")
        batch.drop_constraint("fk_ammo_lots_merged_into", type_="foreignkey")
        batch.drop_column("merged_into_lot_id")
