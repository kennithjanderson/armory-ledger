import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ReferenceNameAuditEvent(Base):
    __tablename__ = "reference_name_audit_events"
    __table_args__ = (
        CheckConstraint(
            "reference_type IN ('manufacturer', 'caliber')",
            name="ck_reference_name_audit_type",
        ),
        CheckConstraint(
            "previous_name <> new_name",
            name="ck_reference_name_audit_changed",
        ),
        Index(
            "ix_reference_name_audit_reference_created",
            "reference_type", "reference_id", "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    # Polymorphic target: manufacturer IDs refer to organizations, caliber IDs
    # refer to calibers. Keep this UUID without a target FK so the history is
    # independent of either reference table's future lifecycle.
    reference_type: Mapped[str] = mapped_column(String(16), nullable=False)
    reference_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )
    previous_name: Mapped[str] = mapped_column(String(255), nullable=False)
    new_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    actor_user = relationship("User")
