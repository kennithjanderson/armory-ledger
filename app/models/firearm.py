import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class FirearmStatus(str, enum.Enum):
    OWNED = "owned"
    DECOMMISSIONED = "decommissioned"
    SOLD = "sold"
    TRANSFERRED = "transferred"
    STOLEN = "stolen"
    LOST = "lost"
    DESTROYED = "destroyed"
    OTHER = "other"

class FirearmType(str, enum.Enum):
    HANDGUN = "handgun"
    RIFLE = "rifle"
    SHOTGUN = "shotgun"
    RECEIVER = "receiver"
    OTHER = "other"
    UNKNOWN = "unknown"

class DatePrecision(str, enum.Enum):
    EXACT = "exact"
    MONTH = "month"
    YEAR = "year"
    APPROXIMATE_YEAR = "approximate_year"
    UNKNOWN = "unknown"


class Firearm(Base):
    __tablename__ = "firearms"

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

    manufacturer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id"),
        nullable=True,
        index=True,
    )

    caliber_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("calibers.id"),
        nullable=True,
        index=True,
    )

    model: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    serial_number: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    firearm_type: Mapped[FirearmType] = mapped_column(
        Enum(
            FirearmType,
            name="firearm_type",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        default=FirearmType.UNKNOWN,
        nullable=False,
    )

    manufacture_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )

    manufacture_date_precision: Mapped[DatePrecision] = mapped_column(
        Enum(
            DatePrecision,
            name="firearm_date_precision",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        default=DatePrecision.UNKNOWN,
        nullable=False,
    )

    obtained_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )

    obtained_date_precision: Mapped[DatePrecision] = mapped_column(
        Enum(
            DatePrecision,
            name="firearm_date_precision",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
            create_type=False,
        ),
        default=DatePrecision.UNKNOWN,
        nullable=False,
    )

    status: Mapped[FirearmStatus] = mapped_column(
        Enum(
            FirearmStatus,
            name="firearm_status",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        default=FirearmStatus.OWNED,
        nullable=False,
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

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    owner = relationship("User")
    manufacturer = relationship("Organization")
    caliber = relationship("Caliber")
