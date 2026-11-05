"""Add ammunition type and shotgun product specifications.

Revision ID: b61a4e70c2d9
Revises: 12ef7a4b9c31
"""
from alembic import op
import sqlalchemy as sa


revision = "b61a4e70c2d9"
down_revision = "12ef7a4b9c31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ammo_products") as batch_op:
        batch_op.add_column(
            sa.Column(
                "ammunition_type",
                sa.String(length=20),
                server_default="rifle_pistol",
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("shell_length_inches", sa.Numeric(4, 2), nullable=True))
        batch_op.add_column(sa.Column("shot_size", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("shot_type", sa.String(length=64), nullable=True))
        batch_op.create_check_constraint(
            "ck_ammo_products_ammunition_type",
            "ammunition_type IN ('rifle_pistol', 'shotgun')",
        )
        batch_op.create_check_constraint(
            "ck_ammo_products_shell_length_positive",
            "shell_length_inches IS NULL OR shell_length_inches > 0",
        )
        batch_op.create_check_constraint(
            "ck_ammo_products_type_specific_fields",
            "(ammunition_type = 'rifle_pistol' AND shell_length_inches IS NULL "
            "AND shot_size IS NULL AND shot_type IS NULL) OR "
            "(ammunition_type = 'shotgun' AND grain_weight IS NULL "
            "AND projectile_type IS NULL)",
        )
    op.create_index(
        "ix_ammo_products_ammunition_type",
        "ammo_products",
        ["ammunition_type"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    has_shotgun_products = bind.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM ammo_products WHERE ammunition_type = 'shotgun')")
    ).scalar()
    if has_shotgun_products:
        raise RuntimeError(
            "Cannot downgrade while shotgun ammunition products would be lost."
        )

    op.drop_index("ix_ammo_products_ammunition_type", table_name="ammo_products")
    with op.batch_alter_table("ammo_products") as batch_op:
        batch_op.drop_constraint("ck_ammo_products_type_specific_fields", type_="check")
        batch_op.drop_constraint("ck_ammo_products_shell_length_positive", type_="check")
        batch_op.drop_constraint("ck_ammo_products_ammunition_type", type_="check")
        batch_op.drop_column("shot_type")
        batch_op.drop_column("shot_size")
        batch_op.drop_column("shell_length_inches")
        batch_op.drop_column("ammunition_type")
