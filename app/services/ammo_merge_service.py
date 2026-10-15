from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.ammo_inventory_transaction import AmmoInventoryTransaction, AmmoTransactionType
from app.models.ammo_lot import AmmoLot
from app.models.ammo_lot_merge import AmmoLotMerge
from app.models.audit_event import AuditEvent
from app.services.ammo_inventory_service import get_physical_inventory, lock_owned_lots
from app.services.ammunition_service import normalize_text


def compatible_lots(source: AmmoLot, destination: AmmoLot) -> bool:
    if (source.id == destination.id or source.owner_id != destination.owner_id
            or source.is_merged or destination.is_merged):
        return False
    left, right = source.ammo_product, destination.ammo_product
    # Brand identity includes manufacturer identity. Do not infer brand aliases.
    if (left.brand_id, left.caliber_id, left.grain_weight) != (
        right.brand_id, right.caliber_id, right.grain_weight
    ):
        return False
    # Existing product matching is whitespace-normalized and case-insensitive.
    def product_text(value):
        return normalize_text(value).lower() if value and value.strip() else None
    for field in ("projectile_type", "product_name", "manufacturer_sku"):
        if product_text(getattr(left, field)) != product_text(getattr(right, field)):
            return False
    # Product notes may carry specifications; conservatively require equality.
    if (left.notes or None) != (right.notes or None):
        return False
    # Manufacturer batch identifiers remain case-sensitive.
    def lot_number(value):
        return normalize_text(value) if value and value.strip() else None
    return lot_number(source.lot_number) == lot_number(destination.lot_number)


def merge_candidates(db: Session, *, source: AmmoLot) -> list[AmmoLot]:
    if source.is_merged or get_physical_inventory(db, lot_id=source.id) <= 0:
        return []
    lots = db.scalars(
        select(AmmoLot).options(joinedload(AmmoLot.ammo_product))
        .where(AmmoLot.owner_id == source.owner_id,
               AmmoLot.merged_into_lot_id.is_(None), AmmoLot.id != source.id)
        .order_by(AmmoLot.created_at, AmmoLot.id)
    ).all()
    return [lot for lot in lots if compatible_lots(source, lot)
            and get_physical_inventory(db, lot_id=lot.id) >= 0]


def merge_lots(db: Session, *, owner_id: UUID, source_id: UUID,
               destination_id: UUID, expected_source: int,
               expected_destination: int) -> AmmoLotMerge:
    if source_id == destination_id:
        raise ValueError("Select two different ammunition lots.")
    try:
        lots = lock_owned_lots(db, owner_id=owner_id, lot_ids=[source_id, destination_id])
        source, destination = lots[source_id], lots[destination_id]
        if not compatible_lots(source, destination):
            raise ValueError("Lots are incompatible or have already been merged.")
        quantity = get_physical_inventory(db, lot_id=source_id)
        destination_balance = get_physical_inventory(db, lot_id=destination_id)
        if quantity <= 0 or destination_balance < 0:
            raise ValueError("Source must contain rounds and destination cannot have a negative balance.")
        if (quantity, destination_balance) != (expected_source, expected_destination):
            raise ValueError("Inventory changed. Reload and review the merge again.")
        now = datetime.now(timezone.utc)
        merge = AmmoLotMerge(owner_id=owner_id, actor_user_id=owner_id,
                             source_lot_id=source_id, destination_lot_id=destination_id,
                             quantity=quantity, created_at=now)
        db.add(merge)
        db.flush()
        for lot, kind, other, direction in [
            (source, AmmoTransactionType.MERGE_OUT, destination, "into"),
            (destination, AmmoTransactionType.MERGE_IN, source, "from"),
        ]:
            transaction = AmmoInventoryTransaction(
                ammo_lot_id=lot.id, merge_id=merge.id, transaction_type=kind,
                quantity=quantity, occurred_at=now,
                notes=f"Merged {direction} lot {other.id}.",
            )
            db.add(transaction)
            db.add(AuditEvent(
                owner_id=owner_id, actor_user_id=owner_id, entity_type="ammo_lot",
                entity_id=lot.id, action=kind.value,
                changes={"merge_id": str(merge.id), "source_lot_id": str(source_id),
                         "destination_lot_id": str(destination_id), "quantity": quantity,
                         "occurred_at": now.isoformat()},
            ))
        source.merged_into_lot_id = destination_id
        db.commit()
        db.refresh(merge)
        return merge
    except Exception:
        db.rollback()
        raise
