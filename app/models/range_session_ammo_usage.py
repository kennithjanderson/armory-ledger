import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RangeAmmoSourceType(str, enum.Enum):
    INVENTORY = "inventory"
    OTHER = "other"


class RangeSessionAmmoUsage(Base):
    __tablename__ = "range_session_ammo_usage"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    range_session_firearm_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "range_session_firearms.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    ammo_lot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ammo_lots.id"),
        nullable=True,
        index=True,
    )

    inventory_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ammo_inventory_transactions.id"),
        nullable=True,
        index=True,
    )

    source_type: Mapped[RangeAmmoSourceType] = mapped_column(
        Enum(
            RangeAmmoSourceType,
            name="range_ammo_source_type",
            values_callable=lambda enum_cls: [
                item.value for item in enum_cls
            ],
        ),
        nullable=False,
        index=True,
    )

    quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    range_session_firearm = relationship(
        "RangeSessionFirearm"
    )

    ammo_lot = relationship("AmmoLot")

    inventory_transaction = relationship(
        "AmmoInventoryTransaction"
    )
