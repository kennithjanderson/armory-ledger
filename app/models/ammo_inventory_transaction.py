import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AmmoTransactionType(str, enum.Enum):
    ACQUIRED = "acquired"
    EXPENDED = "expended"
    GIVEN = "given"
    SOLD = "sold"
    QUARANTINED = "quarantined"
    RELEASED = "released"
    RETURNED = "returned"
    DISPOSED = "disposed"
    ADJUSTMENT_IN = "adjustment_in"
    ADJUSTMENT_OUT = "adjustment_out"


class AmmoInventoryTransaction(Base):
    __tablename__ = "ammo_inventory_transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    ammo_lot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ammo_lots.id"),
        nullable=False,
        index=True,
    )

    transaction_type: Mapped[AmmoTransactionType] = mapped_column(
        Enum(
            AmmoTransactionType,
            name="ammo_transaction_type",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        index=True,
    )

    quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
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

    ammo_lot = relationship("AmmoLot")
