import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AmmoLotMerge(Base):
    __tablename__ = "ammo_lot_merges"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_ammo_lot_merges_quantity"),
        CheckConstraint("source_lot_id <> destination_lot_id", name="ck_ammo_lot_merges_distinct"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    source_lot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ammo_lots.id"), nullable=False, unique=True)
    destination_lot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ammo_lots.id"), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
