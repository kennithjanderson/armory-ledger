import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AmmoProduct(Base):
    __tablename__ = "ammo_products"

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

    grain_weight: Mapped[Decimal | None] = mapped_column(
        Numeric(7, 2),
        nullable=True,
    )

    projectile_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
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
