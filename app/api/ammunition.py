from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from datetime import date

from app.services.ammunition_service import (
    acquire_ammunition,
    update_ammunition,
)

from app.core.config import settings
from app.core.dependencies import get_current_user, get_db
from app.main_templates import templates
from app.models.ammo_product import AmmoProduct
from app.models.ammo_brand import AmmoBrand
from app.models.caliber import Caliber
from app.models.ammo_inventory_transaction import (
    AmmoInventoryTransaction,
    AmmoTransactionType,
)
from app.models.ammo_lot import AmmoLot
from app.models.user import User

from decimal import Decimal

from pydantic import BaseModel, Field

from app.services.ammo_inventory_service import (
    get_physical_inventory,
    record_inventory_activity,
)

router = APIRouter(
    prefix="/ammunition",
    tags=["ammunition"],
)


class AmmunitionAcquisitionRequest(BaseModel):
    brand_name: str = Field(min_length=1, max_length=255)
    caliber_id: UUID
    grain_weight: Decimal | None = Field(
        default=None,
        gt=0,
    )
    projectile_type: str | None = Field(
        default=None,
        max_length=100,
    )
    quantity: int = Field(
        gt=0,
    )
    acquired_date: date
    product_name: str | None = Field(
        default=None,
        max_length=255,
    )
    manufacturer_sku: str | None = Field(
        default=None,
        max_length=100,
    )
    lot_number: str | None = Field(
        default=None,
        max_length=255,
    )
    notes: str | None = None

class AmmunitionUpdateRequest(BaseModel):
    caliber_id: UUID
    grain_weight: Decimal | None = Field(default=None, gt=0)
    projectile_type: str | None = Field(default=None, max_length=100)
    product_name: str | None = Field(default=None, max_length=255)
    manufacturer_sku: str | None = Field(default=None, max_length=100)
    lot_number: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    acquired_date: date | None = None

class AmmunitionActivityRequest(BaseModel):
    transaction_type: AmmoTransactionType
    quantity: int = Field(gt=0)
    occurred_date: date
    notes: str | None = None

@router.get("/")
async def ammunition_list(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    lots = db.scalars(
        select(AmmoLot)
        .join(AmmoLot.ammo_product)
        .join(AmmoProduct.brand)
        .join(AmmoProduct.caliber)
        .options(
            joinedload(AmmoLot.ammo_product)
            .joinedload(AmmoProduct.brand),
            joinedload(AmmoLot.ammo_product)
            .joinedload(AmmoProduct.caliber),
        )
        .where(AmmoLot.owner_id == current_user.id)
        .order_by(
            AmmoBrand.name.asc(),
            Caliber.name.asc(),
            AmmoProduct.grain_weight.asc().nulls_last(),
            AmmoProduct.projectile_type.asc().nulls_last(),
            AmmoLot.id.asc(),
        )
    ).unique().all()

    inventory_by_lot = {}
    acquired_at_by_lot = {}

    for lot in lots:
        inventory_by_lot[lot.id] = get_physical_inventory(
            db,
            lot_id=lot.id,
        )

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

        acquired_at_by_lot[lot.id] = (
            initial_acquisition.occurred_at
            if initial_acquisition
            else None
        )

    return templates.TemplateResponse(
        request=request,
        name="ammunition/list.html",
        context={
            "app_name": settings.app_name,
            "app_version": settings.app_version,
            "current_user": current_user,
            "is_admin": request.session["user"].get(
                "is_admin",
                False,
            ),
            "lots": lots,
            "inventory_by_lot": inventory_by_lot,
            "acquired_at_by_lot": acquired_at_by_lot,
        },
    )

@router.get("/{ammo_lot_id}/edit")
async def ammunition_edit(
    ammo_lot_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    lot = db.scalar(
        select(AmmoLot)
        .options(
            joinedload(AmmoLot.ammo_product)
            .joinedload(AmmoProduct.brand),
            joinedload(AmmoLot.ammo_product)
            .joinedload(AmmoProduct.caliber),
        )
        .where(
            AmmoLot.id == ammo_lot_id,
            AmmoLot.owner_id == current_user.id,
        )
    )

    if lot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ammunition lot not found.",
        )

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

    calibers = db.scalars(
        select(Caliber)
        .where(Caliber.is_selectable.is_(True))
        .order_by(Caliber.name)
    ).all()

    return templates.TemplateResponse(
        request=request,
        name="ammunition/edit.html",
        context={
            "app_name": settings.app_name,
            "app_version": settings.app_version,
            "current_user": current_user,
            "is_admin": request.session["user"].get("is_admin", False),
            "lot": lot,
            "initial_acquisition": initial_acquisition,
            "calibers": calibers,
        },
    )

@router.get("/{ammo_lot_id}/activity/new")
async def ammunition_activity_new(
    ammo_lot_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    lot = db.scalar(
        select(AmmoLot)
        .options(
            joinedload(AmmoLot.ammo_product)
            .joinedload(AmmoProduct.brand),
            joinedload(AmmoLot.ammo_product)
            .joinedload(AmmoProduct.caliber),
        )
        .where(
            AmmoLot.id == ammo_lot_id,
            AmmoLot.owner_id == current_user.id,
        )
    )

    if lot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ammunition lot not found.",
        )

    physical_on_hand = get_physical_inventory(
        db,
        lot_id=lot.id,
    )

    return templates.TemplateResponse(
        request=request,
        name="ammunition/activity_new.html",
        context={
            "app_name": settings.app_name,
            "app_version": settings.app_version,
            "current_user": current_user,
            "is_admin": request.session["user"].get("is_admin", False),
            "lot": lot,
            "physical_on_hand": physical_on_hand,
        },
    )

@router.get("/{ammo_lot_id}")
async def ammunition_detail(
    ammo_lot_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    lot = db.scalar(
        select(AmmoLot)
        .options(
            joinedload(AmmoLot.ammo_product)
            .joinedload(AmmoProduct.brand),
            joinedload(AmmoLot.ammo_product)
            .joinedload(AmmoProduct.caliber),
        )
        .where(
            AmmoLot.id == ammo_lot_id,
            AmmoLot.owner_id == current_user.id,
        )
    )

    if lot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ammunition lot not found.",
        )

    transactions = db.scalars(
        select(AmmoInventoryTransaction)
        .where(
            AmmoInventoryTransaction.ammo_lot_id == lot.id
        )
        .order_by(
            AmmoInventoryTransaction.occurred_at.desc(),
            AmmoInventoryTransaction.created_at.desc(),
        )
    ).all()

    physical_on_hand = get_physical_inventory(
    db,
    lot_id=lot.id,
)

    return templates.TemplateResponse(
        request=request,
        name="ammunition/detail.html",
        context={
            "app_name": settings.app_name,
            "app_version": settings.app_version,
            "current_user": current_user,
            "is_admin": request.session["user"].get("is_admin", False),
            "lot": lot,
            "transactions": transactions,
            "physical_on_hand": physical_on_hand,
        },
    )

@router.post("/")
async def ammunition_acquire(
    payload: AmmunitionAcquisitionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        lot = acquire_ammunition(
            db,
            owner_id=current_user.id,
            brand_name=payload.brand_name,
            caliber_id=payload.caliber_id,
            grain_weight=payload.grain_weight,
            projectile_type=payload.projectile_type,
            quantity=payload.quantity,
            acquired_date=payload.acquired_date,
            product_name=payload.product_name,
            manufacturer_sku=payload.manufacturer_sku,
            lot_number=payload.lot_number,
            notes=payload.notes,
        )
    except ValueError as exc:
        return {
            "success": False,
            "error": str(exc),
        }

    return {
        "success": True,
        "lot": {
            "id": str(lot.id),
        },
    }

@router.put("/{ammo_lot_id}")
async def ammunition_update(
    ammo_lot_id: UUID,
    payload: AmmunitionUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        lot = update_ammunition(
            db,
            lot_id=ammo_lot_id,
            owner_id=current_user.id,
            actor_user_id=current_user.id,
            caliber_id=payload.caliber_id,
            grain_weight=payload.grain_weight,
            projectile_type=payload.projectile_type,
            product_name=payload.product_name,
            manufacturer_sku=payload.manufacturer_sku,
            lot_number=payload.lot_number,
            notes=payload.notes,
            acquired_date=payload.acquired_date,
        )
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ammunition lot not found.",
        )
    except ValueError as exc:
        return {
            "success": False,
            "error": str(exc),
        }

    return {
        "success": True,
        "lot": {
            "id": str(lot.id),
        },
    }

@router.post("/{ammo_lot_id}/activity")
async def ammunition_activity_create(
    ammo_lot_id: UUID,
    payload: AmmunitionActivityRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        transaction = record_inventory_activity(
            db,
            lot_id=ammo_lot_id,
            owner_id=current_user.id,
            actor_user_id=current_user.id,
            transaction_type=payload.transaction_type,
            quantity=payload.quantity,
            occurred_date=payload.occurred_date,
            notes=payload.notes,
        )
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ammunition lot not found.",
        )
    except ValueError as exc:
        return {
            "success": False,
            "error": str(exc),
        }

    return {
        "success": True,
        "transaction": {
            "id": str(transaction.id),
        },
    }