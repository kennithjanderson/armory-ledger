from decimal import Decimal
from uuid import UUID

from datetime import date, datetime, time, timezone
from typing import Any

from app.models.audit_event import AuditEvent

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.ammo_brand import AmmoBrand
from app.models.ammo_inventory_transaction import (
    AmmoInventoryTransaction,
    AmmoTransactionType,
)
from app.models.ammo_lot import AmmoLot
from app.models.ammo_product import AmmoProduct
from app.models.caliber import Caliber
from app.services.manufacturer_service import (
    create_manufacturer,
    find_exact_manufacturer,
)


def normalize_text(value: str) -> str:
    return " ".join(value.strip().split())


def acquire_ammunition(
    db: Session,
    *,
    owner_id: UUID,
    brand_name: str,
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
    cleaned_brand_name = normalize_text(brand_name)

    if not cleaned_brand_name:
        raise ValueError("Brand is required.")

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
        organization = find_exact_manufacturer(
            db,
            cleaned_brand_name,
        )

        if organization is None:
            organization = create_manufacturer(
                db,
                cleaned_brand_name,
                commit=False,
            )

        brand = db.scalar(
            select(AmmoBrand).where(
                AmmoBrand.manufacturer_id == organization.id,
                func.lower(AmmoBrand.name)
                == cleaned_brand_name.lower(),
            )
        )

        if brand is None:
            brand = AmmoBrand(
                manufacturer_id=organization.id,
                name=cleaned_brand_name,
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
    lot = db.scalar(
        select(AmmoLot)
        .where(
            AmmoLot.id == lot_id,
            AmmoLot.owner_id == owner_id,
        )
    )

    if lot is None:
        raise LookupError("Ammunition lot not found.")

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