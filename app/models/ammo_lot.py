import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AmmoLot(Base):
    __tablename__ = "ammo_lots"
    __table_args__ = (
        CheckConstraint(
            "low_inventory_threshold IS NULL OR low_inventory_threshold > 0",
            name="ck_ammo_lots_low_inventory_threshold_positive",
        ),
        CheckConstraint(
            "low_inventory_notifications_enabled = false OR low_inventory_threshold IS NOT NULL",
            name="ck_ammo_lots_low_inventory_enabled_has_threshold",
        ),
    )

    merged_into_lot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ammo_lots.id"), nullable=True, index=True,
    )

    @property
    def is_merged(self) -> bool:
        return self.merged_into_lot_id is not None

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    ammo_product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ammo_products.id"),
        nullable=False,
        index=True,
    )

    lot_number: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    low_inventory_notifications_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
    )
    low_inventory_threshold: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
    )
    depleted_notifications_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    owner = relationship("User")
    ammo_product = relationship("AmmoProduct")
