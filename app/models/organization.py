import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class OrganizationStatus(str, enum.Enum):
    ACTIVE = "active"
    DEFUNCT = "defunct"
    UNKNOWN = "unknown"


class OrganizationRelationshipType(str, enum.Enum):
    OWNED_BY = "owned_by"
    SUBSIDIARY_OF = "subsidiary_of"
    BRAND_OF = "brand_of"
    SUCCESSOR_TO = "successor_to"
    PREDECESSOR_OF = "predecessor_of"
    ACQUIRED_BY = "acquired_by"


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    name: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )

    legal_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    status: Mapped[OrganizationStatus] = mapped_column(
        Enum(
            OrganizationStatus,
            name="organization_status",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        default=OrganizationStatus.UNKNOWN,
        nullable=False,
    )

    website: Mapped[str | None] = mapped_column(
        String(500),
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

    aliases = relationship(
        "OrganizationAlias",
        back_populates="organization",
        cascade="all, delete-orphan",
    )


class ManufacturerProfile(Base):
    __tablename__ = "manufacturer_profiles"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id"),
        primary_key=True,
    )

    is_selectable: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    organization: Mapped["Organization"] = relationship()


class OrganizationRelationship(Base):
    __tablename__ = "organization_relationships"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "related_organization_id",
            "relationship_type",
            "effective_from",
            name="uq_organization_relationship",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )

    related_organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )

    relationship_type: Mapped[OrganizationRelationshipType] = mapped_column(
        Enum(
            OrganizationRelationshipType,
            name="organization_relationship_type",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
    )

    effective_from: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )

    effective_to: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    organization: Mapped["Organization"] = relationship(
        foreign_keys=[organization_id],
    )

    related_organization: Mapped["Organization"] = relationship(
        foreign_keys=[related_organization_id],
    )
