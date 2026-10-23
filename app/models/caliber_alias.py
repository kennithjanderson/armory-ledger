import uuid

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CaliberAlias(Base):
    __tablename__ = "caliber_aliases"
    __table_args__ = (
        UniqueConstraint(
            "alias",
            name="uq_caliber_alias",
        ),
        Index(
            "uq_caliber_aliases_normalized_alias",
            text("lower(trim(alias))"),
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    caliber_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("calibers.id"),
        nullable=False,
        index=True,
    )

    alias: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    caliber: Mapped["Caliber"] = relationship(back_populates="aliases")
