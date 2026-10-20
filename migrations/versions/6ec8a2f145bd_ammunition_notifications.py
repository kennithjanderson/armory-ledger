"""Add per-user ammunition notification channels and per-lot triggers.

Revision ID: 6ec8a2f145bd
Revises: a47c91e2d563
"""
from alembic import op
import sqlalchemy as sa


revision = "6ec8a2f145bd"
down_revision = "a47c91e2d563"
branch_labels = depends_on = None


def upgrade():
    op.add_column("users", sa.Column(
        "ammo_notifications_in_app", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("users", sa.Column(
        "ammo_notifications_email", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("ammo_lots", sa.Column(
        "low_inventory_notifications_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("ammo_lots", sa.Column(
        "low_inventory_threshold", sa.Integer(), nullable=True))
    op.add_column("ammo_lots", sa.Column(
        "depleted_notifications_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_check_constraint(
        "ck_ammo_lots_low_inventory_threshold_positive", "ammo_lots",
        "low_inventory_threshold IS NULL OR low_inventory_threshold > 0")
    op.create_check_constraint(
        "ck_ammo_lots_low_inventory_enabled_has_threshold", "ammo_lots",
        "low_inventory_notifications_enabled = false OR low_inventory_threshold IS NOT NULL")


def downgrade():
    op.drop_constraint("ck_ammo_lots_low_inventory_enabled_has_threshold", "ammo_lots", type_="check")
    op.drop_constraint("ck_ammo_lots_low_inventory_threshold_positive", "ammo_lots", type_="check")
    op.drop_column("ammo_lots", "depleted_notifications_enabled")
    op.drop_column("ammo_lots", "low_inventory_threshold")
    op.drop_column("ammo_lots", "low_inventory_notifications_enabled")
    op.drop_column("users", "ammo_notifications_email")
    op.drop_column("users", "ammo_notifications_in_app")
