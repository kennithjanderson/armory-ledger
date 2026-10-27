"""Owner-directed sharing invitations and section permission checks."""
from datetime import datetime, timezone
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.inventory_share import InventoryShare, InventoryShareAuditEvent
from app.models.notification import NotificationEvent, NotificationRecipient
from app.models.user import User
from app.services import notification_service as notices


SECTIONS = {
    "firearms": "firearms_access",
    "ammunition": "ammunition_access",
    "accessories": "accessories_access",
    "shooting_log": "shooting_log_access",
}
ACCESS_LEVELS = {"none", "ro", "rw"}
MAX_PENDING_INVITATIONS = 20
GENERIC_INVITATION_MESSAGE = "If this address can receive an invitation, one has been queued."


class InvitationEmailUnavailable(ValueError):
    pass


def now_utc():
    return datetime.now(timezone.utc)


def normalize_email(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Enter a valid email address")
    normalized = value.strip()
    notices.mailbox(normalized)
    return normalized


def normalize_permissions(values: dict) -> dict[str, str]:
    if not isinstance(values, dict) or set(values) != set(SECTIONS):
        raise ValueError("Choose an access level for every inventory section")
    normalized = {}
    for section, field in SECTIONS.items():
        value = values[section]
        if value not in ACCESS_LEVELS:
            raise ValueError("Section access must be None, read-only or read-write")
        normalized[field] = value
    if all(value == "none" for value in normalized.values()):
        raise ValueError("Grant access to at least one section")
    return normalized


def permission_summary(share: InventoryShare) -> dict[str, str]:
    return {section: getattr(share, field) for section, field in SECTIONS.items()}


def _audit(db: Session, share: InventoryShare, actor_id, action: str, changes: dict) -> None:
    db.add(InventoryShareAuditEvent(
        share_id=share.id, actor_user_id=actor_id, action=action, changes=changes,
    ))


def invite(db: Session, *, owner: User, email: str, permissions: dict) -> InventoryShare | None:
    """Queue an email invitation; return None for generic, non-actionable cases.

    A pending invitation can target an email before its owner has logged into this
    installation. Its recipient UUID is bound only after an authenticated user
    with that exact email claims it.
    """
    email = normalize_email(email)
    normalized_permissions = normalize_permissions(permissions)
    if not notices.mail_config(db)["enabled"]:
        raise InvitationEmailUnavailable("System email must be enabled to send sharing invitations")

    matching_users = db.scalars(select(User).where(
        func.lower(func.trim(User.email)) == email.lower()
    ).limit(2)).all()
    recipient = matching_users[0] if len(matching_users) == 1 else None
    # Never create an invitation back to the owner, nor allow an ambiguous email
    # to be claimed by multiple accounts.
    if len(matching_users) > 1 or (recipient is not None and recipient.id == owner.id):
        return None

    pending_count = db.scalar(select(func.count()).select_from(InventoryShare).where(
        InventoryShare.owner_id == owner.id,
        InventoryShare.status == "pending",
    )) or 0
    existing = db.scalar(select(InventoryShare).where(
        InventoryShare.owner_id == owner.id,
        func.lower(func.trim(InventoryShare.invite_email)) == email.lower(),
    ).with_for_update())
    if existing is not None and existing.status in ("pending", "accepted"):
        # Repeated submission does not resend mail or silently change an active grant.
        return None
    if existing is None and pending_count >= MAX_PENDING_INVITATIONS:
        raise ValueError("You have reached the pending invitation limit")

    timestamp = now_utc()
    if existing is None:
        share = InventoryShare(
            owner_id=owner.id,
            recipient_id=recipient.id if recipient else None,
            invite_email=email,
            status="pending",
            **normalized_permissions,
            created_at=timestamp,
            updated_at=timestamp,
        )
        db.add(share)
        action = "invited"
    else:
        share = existing
        share.recipient_id = recipient.id if recipient else None
        share.invite_email = email
        share.status = "pending"
        share.accepted_at = None
        share.responded_at = None
        share.revoked_at = None
        share.updated_at = timestamp
        for field, value in normalized_permissions.items():
            setattr(share, field, value)
        action = "reinvited"
    try:
        db.flush()
        _audit(db, share, owner.id, action, {"permissions": normalized_permissions})

        event_key = f"share-invite:{share.id}"
        event = db.scalar(select(NotificationEvent).where(NotificationEvent.event_key == event_key))
        if event is None:
            event = NotificationEvent(
                event_key=event_key,
                kind="share_invitation",
                scope="user",
                severity="info",
                title="Inventory sharing invitation",
                message=("You have an invitation to access selected Armory Ledger inventory sections. "
                         "Sign in to review the requested access and accept or decline. "
                         "This message does not include inventory records."),
                action="/sharing",
                created_at=timestamp,
                updated_at=timestamp,
            )
            db.add(event)
            db.flush()
        else:
            event.resolved = False
            event.updated_at = timestamp
            event.occurrences += 1

        delivery = db.scalar(select(NotificationRecipient).where(
            NotificationRecipient.event_id == event.id
        ))
        target_id = recipient.id if recipient else owner.id
        if delivery is None:
            delivery = NotificationRecipient(
                event_id=event.id,
                user_id=target_id,
                in_app=recipient is not None,
                email_state="pending",
                email_override=email,
                next_attempt=timestamp,
            )
            db.add(delivery)
        else:
            delivery.user_id = target_id
            delivery.in_app = recipient is not None
            delivery.read_at = None
            delivery.email_state = "pending"
            delivery.email_override = email
            delivery.attempts = 0
            delivery.next_attempt = timestamp
            delivery.sent_at = None
            delivery.diagnostic = None
        db.commit()
        db.refresh(share)
        return share
    except IntegrityError:
        db.rollback()
        # A concurrent invite for the same address is deliberately indistinguishable.
        return None
    except Exception:
        db.rollback()
        raise


def claim_pending_invitations(db: Session, user: User) -> int:
    email = normalize_email(user.email)
    matching = db.scalars(select(User.id).where(
        func.lower(func.trim(User.email)) == email.lower()
    ).limit(2)).all()
    if len(matching) != 1:
        return 0

    claimed = 0
    rows = db.scalars(select(InventoryShare).where(
        InventoryShare.status == "pending",
        InventoryShare.recipient_id.is_(None),
        func.lower(func.trim(InventoryShare.invite_email)) == email.lower(),
        InventoryShare.owner_id != user.id,
    ).with_for_update()).all()
    claimed_owners = set()
    for share in rows:
        duplicate = db.scalar(select(InventoryShare.id).where(
            InventoryShare.owner_id == share.owner_id,
            InventoryShare.recipient_id == user.id,
            InventoryShare.id != share.id,
            InventoryShare.status.in_(("pending", "accepted")),
        ))
        if duplicate or share.owner_id in claimed_owners:
            # One owner-recipient pair is allowed. If another old address points
            # to the same account, close the duplicate invitation instead of
            # leaving an unclaimable pending row behind.
            timestamp = now_utc()
            share.status = "declined"
            share.responded_at = timestamp
            share.updated_at = timestamp
            _audit(db, share, user.id, "declined", {"reason": "duplicate_owner_recipient"})
            _resolve_invitation_notice(db, share, timestamp)
            claimed_owners.add(share.owner_id)
            claimed += 1
            continue
        share.recipient_id = user.id
        share.updated_at = now_utc()
        _audit(db, share, user.id, "claimed", {"recipient_bound": True})
        claimed_owners.add(share.owner_id)
        event = db.scalar(select(NotificationEvent).where(
            NotificationEvent.event_key == f"share-invite:{share.id}"
        ))
        if event is not None:
            delivery = db.scalar(select(NotificationRecipient).where(
                NotificationRecipient.event_id == event.id
            ))
            if delivery is not None:
                delivery.user_id = user.id
                delivery.in_app = True
                delivery.read_at = None
        claimed += 1
        db.flush()
    if claimed:
        db.commit()
    else:
        db.rollback()
    return claimed


def set_permissions(db: Session, *, owner_id, share_id, permissions: dict) -> InventoryShare:
    normalized = normalize_permissions(permissions)
    share = db.scalar(select(InventoryShare).where(
        InventoryShare.id == share_id,
        InventoryShare.owner_id == owner_id,
        InventoryShare.status.in_(("pending", "accepted")),
    ).with_for_update())
    if share is None:
        raise LookupError("Sharing invitation not found")
    old = permission_summary(share)
    new = {section: normalized[field] for section, field in SECTIONS.items()}
    if old == new:
        return share
    for field, value in normalized.items():
        setattr(share, field, value)
    share.updated_at = now_utc()
    _audit(db, share, owner_id, "permissions_changed", {"old": old, "new": new})
    db.commit()
    db.refresh(share)
    return share


def revoke(db: Session, *, owner_id, share_id) -> InventoryShare:
    share = db.scalar(select(InventoryShare).where(
        InventoryShare.id == share_id,
        InventoryShare.owner_id == owner_id,
        InventoryShare.status.in_(("pending", "accepted")),
    ).with_for_update())
    if share is None:
        raise LookupError("Sharing invitation not found")
    timestamp = now_utc()
    previous_status = share.status
    share.status = "revoked"
    share.revoked_at = timestamp
    share.responded_at = timestamp
    share.updated_at = timestamp
    _audit(db, share, owner_id, "revoked", {"previous_status": previous_status})
    _resolve_invitation_notice(db, share, timestamp)
    db.commit()
    db.refresh(share)
    return share


def respond(db: Session, *, recipient: User, share_id, accept: bool) -> InventoryShare:
    try:
        claim_pending_invitations(db, recipient)
    except ValueError:
        # A previously bound account can still respond if its current identity
        # provider email claim is temporarily unusable; unbound claims cannot.
        pass
    share = db.scalar(select(InventoryShare).where(
        InventoryShare.id == share_id,
        InventoryShare.recipient_id == recipient.id,
        InventoryShare.status == "pending",
    ).with_for_update())
    if share is None:
        raise LookupError("Invitation not found")
    timestamp = now_utc()
    if accept:
        share.status = "accepted"
        share.accepted_at = timestamp
        action = "accepted"
    else:
        share.status = "declined"
        action = "declined"
    share.responded_at = timestamp
    share.updated_at = timestamp
    _audit(db, share, recipient.id, action, {"status": share.status})
    _resolve_invitation_notice(db, share, timestamp)
    db.commit()
    db.refresh(share)
    return share


def _resolve_invitation_notice(db: Session, share: InventoryShare, timestamp: datetime) -> None:
    event = db.scalar(select(NotificationEvent).where(
        NotificationEvent.event_key == f"share-invite:{share.id}"
    ))
    if event is None:
        return
    event.resolved = True
    event.updated_at = timestamp
    delivery = db.scalar(select(NotificationRecipient).where(
        NotificationRecipient.event_id == event.id
    ))
    if delivery is not None:
        delivery.read_at = delivery.read_at or timestamp
        if delivery.email_state in ("pending", "retry"):
            delivery.email_state = "cancelled"
            delivery.diagnostic = "Invitation is no longer pending"


def section_access(db: Session, *, owner_id, actor_id, section: str) -> str:
    """Resolve None/RO/RW for one owner and actor; admin status grants no bypass."""
    if section not in SECTIONS:
        raise ValueError("Unknown inventory sharing section")
    if owner_id == actor_id:
        return "rw"
    field = SECTIONS[section]
    share = db.scalar(select(InventoryShare).where(
        InventoryShare.owner_id == owner_id,
        InventoryShare.recipient_id == actor_id,
        InventoryShare.status == "accepted",
    ))
    return getattr(share, field) if share is not None else "none"


def require_section_access(db: Session, *, owner_id, actor_id, section: str, write: bool = False) -> str:
    access = section_access(db, owner_id=owner_id, actor_id=actor_id, section=section)
    if access == "none" or (write and access != "rw"):
        raise PermissionError("Inventory section access denied")
    return access
