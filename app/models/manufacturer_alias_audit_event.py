import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ManufacturerAliasAuditEvent(Base):
    __tablename__ = "manufacturer_alias_audit_events"
    __table_args__ = (
        CheckConstraint(
            "action IN ('created', 'updated', 'deleted')",
            name="ck_manufacturer_alias_audit_action",
        ),
        CheckConstraint(
            "(action = 'created' AND previous_alias IS NULL AND new_alias IS NOT NULL) "
            "OR (action = 'updated' AND previous_alias IS NOT NULL AND new_alias IS NOT NULL) "
            "OR (action = 'deleted' AND previous_alias IS NOT NULL AND new_alias IS NULL)",
            name="ck_manufacturer_alias_audit_values",
        ),
        Index("ix_manufacturer_alias_audit_manufacturer_created", "manufacturer_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    manufacturer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False,
    )
    # Kept without a foreign key so deletion does not erase the audit target.
    alias_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    previous_alias: Mapped[str | None] = mapped_column(String(255), nullable=True)
    new_alias: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    manufacturer = relationship("Organization")
    actor_user = relationship("User")
