from decimal import Decimal
from uuid import UUID

from datetime import date, datetime, time, timezone
from typing import Any

from app.models.audit_event import AuditEvent

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.ammo_brand import AmmoBrand
from app.models.ammo_inventory_transaction import (
    AmmoInventoryTransaction,
    AmmoTransactionType,
)
from app.models.ammo_lot import AmmoLot
from app.models.ammo_product import AmmoProduct
from app.models.caliber import Caliber
from app.models.organization import ManufacturerProfile, Organization
from app.services.ammo_inventory_service import get_physical_inventory


def normalize_text(value: str) -> str:
    return " ".join(value.strip().split())


def find_duplicate_ammunition_lots(
    db: Session,
    *,
    owner_id: UUID,
    manufacturer_id: UUID,
    caliber_id: UUID,
    grain_weight: Decimal | None,
    projectile_type: str | None,
) -> list[tuple[AmmoLot, int]]:
    """Find exact, owner-scoped lots that can be replenished without a lot number.

    Product name and SKU are intentionally ignored: suggestions follow the four
    ammunition characteristics used by the acquisition workflow. Whitespace-only
    manufacturer lot numbers count as absent, and depleted lots remain eligible.
    """
    conditions = [
        AmmoLot.owner_id == owner_id,
        AmmoLot.merged_into_lot_id.is_(None),
        AmmoProduct.caliber_id == caliber_id,
        AmmoBrand.manufacturer_id == manufacturer_id,
        or_(AmmoLot.lot_number.is_(None), func.trim(AmmoLot.lot_number) == ""),
    ]
    if grain_weight is None:
        conditions.append(AmmoProduct.grain_weight.is_(None))
    else:
        conditions.append(AmmoProduct.grain_weight == grain_weight)

    candidates = db.scalars(
        select(AmmoLot)
        .join(AmmoProduct, AmmoProduct.id == AmmoLot.ammo_product_id)
        .join(AmmoBrand, AmmoBrand.id == AmmoProduct.brand_id)
        .where(*conditions)
        .order_by(AmmoLot.created_at, AmmoLot.id)
    ).all()
    expected_projectile = normalize_text(projectile_type or "").casefold()
    matches: list[tuple[AmmoLot, int]] = []
    for lot in candidates:
        actual_projectile = normalize_text(
            lot.ammo_product.projectile_type or ""
        ).casefold()
        if actual_projectile == expected_projectile:
            matches.append((lot, get_physical_inventory(db, lot_id=lot.id)))
    return matches


def acquire_ammunition(
    db: Session,
    *,
    owner_id: UUID,
    manufacturer_id: UUID,
    caliber_id: UUID,
    grain_weight: Decimal | None,
    projectile_type: str | None,
    quantity: int,
    acquired_date: date,
    product_name: str | None = None,
    manufacturer_sku: str | None = None,
    lot_number: str | None = None,
    notes: str | None = None,
) -> AmmoLot:
    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero.")

    if grain_weight is not None and grain_weight <= 0:
        raise ValueError("Grain weight must be greater than zero.")

    caliber = db.scalar(
        select(Caliber).where(
            Caliber.id == caliber_id,
            Caliber.is_selectable.is_(True),
        )
    )

    if caliber is None:
        raise ValueError("Selected caliber is invalid.")

    manufacturer = db.scalar(
        select(Organization)
        .join(ManufacturerProfile, ManufacturerProfile.organization_id == Organization.id)
        .where(
            Organization.id == manufacturer_id,
            ManufacturerProfile.is_selectable.is_(True),
        )
    )
    if manufacturer is None:
        raise ValueError("Selected manufacturer is invalid.")

    cleaned_projectile_type = (
        normalize_text(projectile_type)
        if projectile_type
        else None
    )

    cleaned_product_name = (
        normalize_text(product_name)
        if product_name
        else None
    )

    cleaned_manufacturer_sku = (
        normalize_text(manufacturer_sku)
        if manufacturer_sku
        else None
    )

    cleaned_lot_number = (
        normalize_text(lot_number)
        if lot_number
        else None
    )

    cleaned_notes = notes.strip() if notes and notes.strip() else None

    try:
        brand = db.scalar(
            select(AmmoBrand).where(
                AmmoBrand.manufacturer_id == manufacturer.id,
                func.lower(AmmoBrand.name)
                == manufacturer.name.lower(),
            )
        )

        if brand is None:
            brand = AmmoBrand(
                manufacturer_id=manufacturer.id,
                name=manufacturer.name,
            )
            db.add(brand)
            db.flush()

        product_conditions = [
            AmmoProduct.brand_id == brand.id,
            AmmoProduct.caliber_id == caliber.id,
        ]

        if grain_weight is None:
            product_conditions.append(
                AmmoProduct.grain_weight.is_(None)
            )
        else:
            product_conditions.append(
                AmmoProduct.grain_weight == grain_weight
            )

        if cleaned_projectile_type is None:
            product_conditions.append(
                AmmoProduct.projectile_type.is_(None)
            )
        else:
            product_conditions.append(
                func.lower(AmmoProduct.projectile_type)
                == cleaned_projectile_type.lower()
            )

        if cleaned_product_name is None:
            product_conditions.append(
                AmmoProduct.product_name.is_(None)
            )
        else:
            product_conditions.append(
                func.lower(AmmoProduct.product_name)
                == cleaned_product_name.lower()
            )

        if cleaned_manufacturer_sku is None:
            product_conditions.append(
                AmmoProduct.manufacturer_sku.is_(None)
            )
        else:
            product_conditions.append(
                func.lower(AmmoProduct.manufacturer_sku)
                == cleaned_manufacturer_sku.lower()
            )

        product = db.scalar(
            select(AmmoProduct).where(*product_conditions)
        )

        if product is None:
            product = AmmoProduct(
                brand_id=brand.id,
                caliber_id=caliber.id,
                grain_weight=grain_weight,
                projectile_type=cleaned_projectile_type,
                product_name=cleaned_product_name,
                manufacturer_sku=cleaned_manufacturer_sku,
            )
            db.add(product)
            db.flush()

        lot = AmmoLot(
            owner_id=owner_id,
            ammo_product_id=product.id,
            lot_number=cleaned_lot_number,
            notes=cleaned_notes,
        )

        db.add(lot)
        db.flush()

        transaction = AmmoInventoryTransaction(
            ammo_lot_id=lot.id,
            transaction_type=AmmoTransactionType.ACQUIRED,
            quantity=quantity,
            occurred_at=datetime.combine(
                acquired_date,
                time(hour=12),
                tzinfo=timezone.utc,
            ),
            notes="Initial inventory acquisition.",
        )

        db.add(transaction)

        db.commit()
        db.refresh(lot)

        return lot

    except Exception:
        db.rollback()
        raise

def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = normalize_text(value)
    return normalized or None


def update_ammunition(
    db: Session,
    *,
    lot_id: UUID,
    owner_id: UUID,
    actor_user_id: UUID,
    caliber_id: UUID,
    grain_weight: Decimal | None,
    projectile_type: str | None,
    product_name: str | None,
    manufacturer_sku: str | None,
    lot_number: str | None,
    notes: str | None,
    acquired_date: date | None,
) -> AmmoLot:
    from app.services.ammo_inventory_service import lock_owned_lots

    lot = lock_owned_lots(db, owner_id=owner_id, lot_ids=[lot_id])[lot_id]
    if lot.is_merged:
        raise ValueError("Merged ammunition lots are read-only.")

    current_product = db.get(AmmoProduct, lot.ammo_product_id)

    if current_product is None:
        raise ValueError("Ammunition product not found.")

    caliber = db.scalar(
        select(Caliber).where(
            Caliber.id == caliber_id,
            Caliber.is_selectable.is_(True),
        )
    )

    if caliber is None:
        raise ValueError("Invalid caliber.")

    if grain_weight is not None and grain_weight <= 0:
        raise ValueError("Grain weight must be greater than zero.")

    projectile_type = _optional_text(projectile_type)
    product_name = _optional_text(product_name)
    manufacturer_sku = _optional_text(manufacturer_sku)
    lot_number = _optional_text(lot_number)

    if notes is not None:
        notes = notes.strip() or None

    initial_acquisition = db.scalar(
        select(AmmoInventoryTransaction)
        .where(
            AmmoInventoryTransaction.ammo_lot_id == lot.id,
            AmmoInventoryTransaction.transaction_type
            == AmmoTransactionType.ACQUIRED,
        )
        .order_by(AmmoInventoryTransaction.created_at.asc())
        .limit(1)
    )

    changes: dict[str, Any] = {}

    def record_change(field: str, old: Any, new: Any) -> None:
        if old != new:
            changes[field] = {
                "old": str(old) if old is not None else None,
                "new": str(new) if new is not None else None,
            }

    record_change(
        "caliber",
        str(current_product.caliber_id),
        str(caliber_id),
    )
    record_change(
        "grain_weight",
        current_product.grain_weight,
        grain_weight,
    )
    record_change(
        "projectile_type",
        current_product.projectile_type,
        projectile_type,
    )
    record_change(
        "product_name",
        current_product.product_name,
        product_name,
    )
    record_change(
        "manufacturer_sku",
        current_product.manufacturer_sku,
        manufacturer_sku,
    )
    record_change("lot_number", lot.lot_number, lot_number)
    record_change("notes", lot.notes, notes)

    if initial_acquisition is not None and acquired_date is not None:
        record_change(
            "acquired_date",
            initial_acquisition.occurred_at.date(),
            acquired_date,
        )

    if not changes:
        return lot

    product_conditions = [
        AmmoProduct.brand_id == current_product.brand_id,
        AmmoProduct.caliber_id == caliber_id,
    ]

    if grain_weight is None:
        product_conditions.append(AmmoProduct.grain_weight.is_(None))
    else:
        product_conditions.append(AmmoProduct.grain_weight == grain_weight)

    for column, value in (
        (AmmoProduct.projectile_type, projectile_type),
        (AmmoProduct.product_name, product_name),
        (AmmoProduct.manufacturer_sku, manufacturer_sku),
    ):
        if value is None:
            product_conditions.append(column.is_(None))
        else:
            product_conditions.append(
                func.lower(column) == value.lower()
            )

    target_product = db.scalar(
        select(AmmoProduct).where(*product_conditions).limit(1)
    )

    if target_product is None:
        target_product = AmmoProduct(
            brand_id=current_product.brand_id,
            caliber_id=caliber_id,
            grain_weight=grain_weight,
            projectile_type=projectile_type,
            product_name=product_name,
            manufacturer_sku=manufacturer_sku,
        )
        db.add(target_product)
        db.flush()

    lot.ammo_product_id = target_product.id
    lot.lot_number = lot_number
    lot.notes = notes

    if initial_acquisition is not None and acquired_date is not None:
        initial_acquisition.occurred_at = datetime.combine(
            acquired_date,
            time(hour=12),
            tzinfo=timezone.utc,
        )

    db.add(
        AuditEvent(
            owner_id=owner_id,
            actor_user_id=actor_user_id,
            entity_type="ammo_lot",
            entity_id=lot.id,
            action="updated",
            changes=changes,
        )
    )

    try:
        db.commit()
        db.refresh(lot)
    except Exception:
        db.rollback()
        raise

    return lot
