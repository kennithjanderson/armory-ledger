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

INVENTORY_IN_TYPES = {
    AmmoTransactionType.ACQUIRED,
    AmmoTransactionType.RETURNED,
    AmmoTransactionType.ADJUSTMENT_IN,
}

INVENTORY_OUT_TYPES = {
    AmmoTransactionType.EXPENDED,
    AmmoTransactionType.GIVEN,
    AmmoTransactionType.SOLD,
    AmmoTransactionType.DISPOSED,
    AmmoTransactionType.ADJUSTMENT_OUT,
}

MANUAL_ACTIVITY_TYPES = INVENTORY_IN_TYPES | INVENTORY_OUT_TYPES


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
) -> AmmoInventoryTransaction:
    lot = db.scalar(
        select(AmmoLot).where(
            AmmoLot.id == lot_id,
            AmmoLot.owner_id == owner_id,
        )
    )

    if lot is None:
        raise LookupError("Ammunition lot not found.")

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

    audit_event = AuditEvent(
    owner_id=owner_id,
    actor_user_id=actor_user_id,
    entity_type="ammo_lot",
    entity_id=lot.id,
    action="inventory_activity",
    changes={
        "transaction_id": str(transaction.id),
        "transaction_type": transaction_type.value,
        "quantity": quantity,
        "occurred_date": occurred_date.isoformat(),
        "notes": notes,
    },
)

    db.add(audit_event)

    try:
        db.commit()
        db.refresh(transaction)
    except Exception:
        db.rollback()
        raise

    return transaction
