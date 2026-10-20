from datetime import date, datetime, time, timezone
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.ammo_inventory_transaction import (
    AmmoInventoryTransaction,
    AmmoTransactionType,
)
from app.models.ammo_lot import AmmoLot

from app.models.audit_event import AuditEvent
from app.models.range_session import RangeSession
from app.models.range_session_firearm import RangeSessionFirearm
from app.models.range_session_ammo_usage import RangeSessionAmmoUsage

INVENTORY_IN_TYPES = {
    AmmoTransactionType.ACQUIRED,
    AmmoTransactionType.RETURNED,
    AmmoTransactionType.ADJUSTMENT_IN,
    AmmoTransactionType.MERGE_IN,
}

INVENTORY_OUT_TYPES = {
    AmmoTransactionType.EXPENDED,
    AmmoTransactionType.GIVEN,
    AmmoTransactionType.SOLD,
    AmmoTransactionType.DISPOSED,
    AmmoTransactionType.ADJUSTMENT_OUT,
    AmmoTransactionType.MERGE_OUT,
}

MANUAL_ACTIVITY_TYPES = (INVENTORY_IN_TYPES | INVENTORY_OUT_TYPES) - {
    AmmoTransactionType.MERGE_IN, AmmoTransactionType.MERGE_OUT,
}


def shooting_expenditure_descriptions(db: Session, *, owner_id: UUID, transaction_ids) -> dict:
    """Display current classification only for uniquely linked expenditures.

    Stored transaction notes and audits are never changed. Missing/ambiguous links
    retain their original text, including removed historical usage records.
    """
    if not transaction_ids:
        return {}
    rows = db.execute(
        select(AmmoInventoryTransaction.id, RangeSession.id, RangeSession.activity_type)
        .join(AmmoLot, AmmoInventoryTransaction.ammo_lot_id == AmmoLot.id)
        .join(RangeSessionAmmoUsage,
              RangeSessionAmmoUsage.inventory_transaction_id == AmmoInventoryTransaction.id)
        .join(RangeSessionFirearm,
              RangeSessionAmmoUsage.range_session_firearm_id == RangeSessionFirearm.id)
        .join(RangeSession, RangeSessionFirearm.range_session_id == RangeSession.id)
        .where(AmmoInventoryTransaction.id.in_(transaction_ids),
               AmmoInventoryTransaction.transaction_type == AmmoTransactionType.EXPENDED,
               AmmoLot.owner_id == owner_id, RangeSession.owner_id == owner_id)
    ).all()
    linked = {}
    for transaction_id, session_id, activity_type in rows:
        linked.setdefault(transaction_id, {})[session_id] = activity_type
    return {transaction_id: next(iter(sessions.values())).expenditure_description
            for transaction_id, sessions in linked.items() if len(sessions) == 1}


def lock_owned_lots(db: Session, *, owner_id: UUID, lot_ids) -> dict[UUID, AmmoLot]:
    """All writers lock lot rows in UUID order before reading balances/status."""
    ids = set(lot_ids)
    if not ids:
        return {}
    lots = db.scalars(
        select(AmmoLot)
        .where(AmmoLot.owner_id == owner_id, AmmoLot.id.in_(ids))
        .order_by(AmmoLot.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    if len(lots) != len(ids):
        raise LookupError("Ammunition lot not found.")
    return {lot.id: lot for lot in lots}


def get_physical_inventory(
    db: Session,
    *,
    lot_id: UUID,
) -> int:
    quantity = db.scalar(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (
                            AmmoInventoryTransaction.transaction_type.in_(
                                INVENTORY_IN_TYPES
                            ),
                            AmmoInventoryTransaction.quantity,
                        ),
                        (
                            AmmoInventoryTransaction.transaction_type.in_(
                                INVENTORY_OUT_TYPES
                            ),
                            -AmmoInventoryTransaction.quantity,
                        ),
                        else_=0,
                    )
                ),
                0,
            )
        ).where(
            AmmoInventoryTransaction.ammo_lot_id == lot_id
        )
    )

    return int(quantity or 0)


def queue_inventory_transition(
    db: Session, *, lot_id: UUID, transaction_id: UUID, before: int, after: int,
) -> None:
    """Add any qualifying private notice to the caller's transaction."""
    lot = db.get(AmmoLot, lot_id)
    if lot is None:
        return
    from app.services.notification_service import ammunition_inventory_transition
    ammunition_inventory_transition(
        db, lot=lot, transaction_id=transaction_id, before=before, after=after,
    )


def record_inventory_activity(
    db: Session,
    *,
    lot_id: UUID,
    owner_id: UUID,
    actor_user_id: UUID,
    transaction_type: AmmoTransactionType,
    quantity: int,
    occurred_date: date,
    notes: str | None = None,
    audit_context: dict | None = None,
    commit: bool = True,
    notify_transition: bool = True,
) -> AmmoInventoryTransaction:
    lot = lock_owned_lots(db, owner_id=owner_id, lot_ids=[lot_id])[lot_id]
    if lot.is_merged:
        raise ValueError("Merged ammunition lots cannot receive inventory activity.")

    if transaction_type not in MANUAL_ACTIVITY_TYPES:
        raise ValueError("Invalid inventory activity type.")

    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero.")

    physical_on_hand = get_physical_inventory(
        db,
        lot_id=lot.id,
    )

    if (
        transaction_type in INVENTORY_OUT_TYPES
        and quantity > physical_on_hand
    ):
        raise ValueError(
            f"Cannot remove {quantity} rounds. "
            f"Only {physical_on_hand} rounds are currently on hand."
        )

    notes = notes.strip() if notes else None
    notes = notes or None

    transaction = AmmoInventoryTransaction(
        ammo_lot_id=lot.id,
        transaction_type=transaction_type,
        quantity=quantity,
        occurred_at=datetime.combine(
            occurred_date,
            time(hour=12),
            tzinfo=timezone.utc,
        ),
        notes=notes,
    )

    db.add(transaction)
    db.flush()

    audit_changes = {
        "transaction_id": str(transaction.id),
        "transaction_type": transaction_type.value,
        "quantity": quantity,
        "occurred_date": occurred_date.isoformat(),
        "notes": notes,
    }

    if audit_context:
        audit_changes.update(audit_context)

    audit_event = AuditEvent(
        owner_id=owner_id,
        actor_user_id=actor_user_id,
        entity_type="ammo_lot",
        entity_id=lot.id,
        action="inventory_activity",
        changes=audit_changes,
    )

    db.add(audit_event)

    if notify_transition:
        queue_inventory_transition(
            db, lot_id=lot.id, transaction_id=transaction.id,
            before=physical_on_hand,
            after=get_physical_inventory(db, lot_id=lot.id),
        )

    if commit:
        try:
            db.commit()
            db.refresh(transaction)
        except Exception:
            db.rollback()
            raise

    return transaction
