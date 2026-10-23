import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CaliberAliasAuditEvent(Base):
    __tablename__ = "caliber_alias_audit_events"
    __table_args__ = (
        CheckConstraint(
            "action IN ('created', 'deleted')",
            name="ck_caliber_alias_audit_action",
        ),
        CheckConstraint(
            "(action = 'created' AND previous_alias IS NULL AND new_alias IS NOT NULL) "
            "OR (action = 'deleted' AND previous_alias IS NOT NULL AND new_alias IS NULL)",
            name="ck_caliber_alias_audit_values",
        ),
        Index("ix_caliber_alias_audit_caliber_created", "caliber_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    caliber_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calibers.id", ondelete="RESTRICT"), nullable=False,
    )
    # Keep history after an alias row is removed.
    alias_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    previous_alias: Mapped[str | None] = mapped_column(String(100), nullable=True)
    new_alias: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    caliber = relationship("Caliber")
    actor_user = relationship("User")
