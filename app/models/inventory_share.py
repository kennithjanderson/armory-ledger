"""Owner-controlled, directional inventory sharing grants."""
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint,
    func, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class InventoryShare(Base):
    __tablename__ = "inventory_shares"
    __table_args__ = (
        UniqueConstraint("owner_id", "recipient_id", name="uq_inventory_shares_owner_recipient"),
        CheckConstraint("owner_id <> recipient_id OR recipient_id IS NULL", name="ck_inventory_shares_not_self"),
        CheckConstraint("status IN ('pending', 'accepted', 'declined', 'revoked')", name="ck_inventory_shares_status"),
        CheckConstraint("firearms_access IN ('none', 'ro', 'rw')", name="ck_inventory_shares_firearms_access"),
        CheckConstraint("ammunition_access IN ('none', 'ro', 'rw')", name="ck_inventory_shares_ammunition_access"),
        CheckConstraint("accessories_access IN ('none', 'ro', 'rw')", name="ck_inventory_shares_accessories_access"),
        CheckConstraint("shooting_log_access IN ('none', 'ro', 'rw')", name="ck_inventory_shares_shooting_log_access"),
        CheckConstraint(
            "firearms_access <> 'none' OR ammunition_access <> 'none' OR "
            "accessories_access <> 'none' OR shooting_log_access <> 'none'",
            name="ck_inventory_shares_has_access",
        ),
        CheckConstraint(
            "status <> 'accepted' OR (recipient_id IS NOT NULL AND accepted_at IS NOT NULL)",
            name="ck_inventory_shares_accepted_has_recipient",
        ),
        Index(
            "uq_inventory_shares_owner_active_email",
            "owner_id", func.lower(func.trim(text("invite_email"))), unique=True,
            postgresql_where=text("status IN ('pending', 'accepted')"),
            sqlite_where=text("status IN ('pending', 'accepted')"),
        ),
        Index("ix_inventory_shares_recipient_status", "recipient_id", "status"),
        Index("ix_inventory_shares_owner_status", "owner_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    # NULL until an authenticated Armory User logs in with the invited email.
    recipient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True,
    )
    invite_email: Mapped[str] = mapped_column(String(320), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending")
    firearms_access: Mapped[str] = mapped_column(String(5), nullable=False, default="none", server_default="none")
    ammunition_access: Mapped[str] = mapped_column(String(5), nullable=False, default="none", server_default="none")
    accessories_access: Mapped[str] = mapped_column(String(5), nullable=False, default="none", server_default="none")
    shooting_log_access: Mapped[str] = mapped_column(String(5), nullable=False, default="none", server_default="none")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    owner = relationship("User", foreign_keys=[owner_id])
    recipient = relationship("User", foreign_keys=[recipient_id])

    def permission(self, section: str) -> str:
        field = {
            "firearms": self.firearms_access,
            "ammunition": self.ammunition_access,
            "accessories": self.accessories_access,
            "shooting_log": self.shooting_log_access,
        }.get(section)
        if field is None:
            raise ValueError("Unknown inventory sharing section")
        return field


class InventoryShareAuditEvent(Base):
    __tablename__ = "inventory_share_audit_events"
    __table_args__ = (
        CheckConstraint(
            "action IN ('invited', 'reinvited', 'claimed', 'permissions_changed', 'accepted', 'declined', 'revoked')",
            name="ck_inventory_share_audit_action",
        ),
        Index("ix_inventory_share_audit_share_created", "share_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    share_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_shares.id", ondelete="CASCADE"), nullable=False,
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    changes: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    share = relationship("InventoryShare")
    actor = relationship("User")
