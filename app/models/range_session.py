import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ShootingActivityType(str, enum.Enum):
    RANGE = "range"
    HUNTING = "hunting"
    TRAINING = "training"
    DEFENSIVE = "defensive"
    OTHER = "other"

    @property
    def label(self) -> str:
        return {
            "range": "Range Session",
            "hunting": "Hunting",
            "training": "Training",
            "defensive": "Defensive Action",
            "other": "Other",
        }[self.value]

    @property
    def expenditure_description(self) -> str:
        label = "Other shooting activity" if self is self.OTHER else self.label.capitalize()
        return f"{label} expenditure."


class RangeSession(Base):
    __tablename__ = "range_sessions"

    activity_type: Mapped[ShootingActivityType] = mapped_column(
        Enum(
            ShootingActivityType,
            native_enum=False,
            length=20,
            create_constraint=True,
            validate_strings=True,
            name="ck_range_sessions_activity_type",
            values_callable=lambda cls: [item.value for item in cls],
        ),
        default=ShootingActivityType.RANGE,
        server_default="range",
        nullable=False,
    )

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

    occurred_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )

    location: Mapped[str | None] = mapped_column(
        String(255),
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

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    owner = relationship("User")
