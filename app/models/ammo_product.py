import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AmmoProduct(Base):
    __tablename__ = "ammo_products"
    __table_args__ = (
        CheckConstraint(
            "ammunition_type IN ('rifle_pistol', 'shotgun')",
            name="ck_ammo_products_ammunition_type",
        ),
        CheckConstraint(
            "shell_length_inches IS NULL OR shell_length_inches > 0",
            name="ck_ammo_products_shell_length_positive",
        ),
        CheckConstraint(
            "(ammunition_type = 'rifle_pistol' AND shell_length_inches IS NULL "
            "AND shot_size IS NULL AND shot_type IS NULL) OR "
            "(ammunition_type = 'shotgun' AND grain_weight IS NULL "
            "AND projectile_type IS NULL)",
            name="ck_ammo_products_type_specific_fields",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    brand_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ammo_brands.id"),
        nullable=False,
        index=True,
    )

    caliber_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("calibers.id"),
        nullable=False,
        index=True,
    )

    ammunition_type: Mapped[str] = mapped_column(
        String(20),
        default="rifle_pistol",
        server_default="rifle_pistol",
        nullable=False,
        index=True,
    )

    grain_weight: Mapped[Decimal | None] = mapped_column(
        Numeric(7, 2),
        nullable=True,
    )

    projectile_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )

    shell_length_inches: Mapped[Decimal | None] = mapped_column(
        Numeric(4, 2),
        nullable=True,
    )

    shot_size: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )

    shot_type: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    product_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    manufacturer_sku: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    brand = relationship("AmmoBrand")
    caliber = relationship("Caliber")
