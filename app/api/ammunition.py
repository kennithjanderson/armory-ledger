from uuid import UUID
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from datetime import date

from app.services.ammunition_service import (
    acquire_ammunition,
    find_duplicate_ammunition_lots,
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
from app.models.ammo_lot_merge import AmmoLotMerge
from app.models.organization import Organization
from app.services.ammo_merge_service import merge_candidates, merge_lots
from app.core.csrf import csrf_token, require_csrf
from app.models.user import User

from decimal import Decimal

from pydantic import BaseModel, Field

from app.services.ammo_inventory_service import (
    get_physical_inventory,
    record_inventory_activity,
    shooting_expenditure_descriptions,
)

from app.models.firearm import Firearm
from app.models.range_session import RangeSession
from app.models.range_session_firearm import RangeSessionFirearm
from app.models.range_session_ammo_usage import RangeSessionAmmoUsage

router = APIRouter(
    prefix="/ammunition",
    tags=["ammunition"],
)


def _group_lots_by_manufacturer(lots: list[AmmoLot]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for lot in lots:
        manufacturer = lot.ammo_product.brand.manufacturer
        group = grouped.setdefault(
            str(manufacturer.id),
            {"manufacturer": manufacturer.name, "lots": []},
        )
        group["lots"].append(lot)

    def lot_key(lot: AmmoLot):
        product = lot.ammo_product
        return (
            product.grain_weight is None,
            product.grain_weight or Decimal("0"),
            (product.projectile_type or "").casefold(),
            (lot.lot_number or "").casefold(),
            str(lot.id),
        )

    groups = list(grouped.values())
    for group in groups:
        group["lots"].sort(key=lot_key)
    return sorted(
        groups,
        key=lambda group: (
            group["manufacturer"].casefold(),
            group["manufacturer"],
        ),
    )


class AmmunitionAcquisitionRequest(BaseModel):
    manufacturer_id: UUID
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
    create_separate_lot: bool = False

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

class AmmunitionNotificationSettingsRequest(BaseModel):
    low_inventory_notifications_enabled: bool
    low_inventory_threshold: int | None = Field(default=None, gt=0, le=2_147_483_647)
    depleted_notifications_enabled: bool

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
            .joinedload(AmmoProduct.brand)
            .joinedload(AmmoBrand.manufacturer),
            joinedload(AmmoLot.ammo_product)
            .joinedload(AmmoProduct.caliber),
        )
        .where(AmmoLot.owner_id == current_user.id, AmmoLot.merged_into_lot_id.is_(None))
        .order_by(
            Caliber.name.asc(),
            AmmoBrand.name.asc(),
            AmmoProduct.grain_weight.asc().nulls_last(),
            AmmoProduct.projectile_type.asc().nulls_last(),
            AmmoLot.id.asc(),
        )
    ).unique().all()

    caliber_summaries_by_id = {}

    for lot in lots:
        caliber = lot.ammo_product.caliber

        if caliber.id not in caliber_summaries_by_id:
            caliber_summaries_by_id[caliber.id] = {
                "caliber": caliber,
                "lot_count": 0,
                "quantity": 0,
            }

        caliber_summaries_by_id[
            caliber.id
        ]["lot_count"] += 1

        caliber_summaries_by_id[
            caliber.id
        ]["quantity"] += get_physical_inventory(
            db,
            lot_id=lot.id,
        )

    caliber_summaries = list(
        caliber_summaries_by_id.values()
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
            "caliber_summaries": caliber_summaries,
        },
    )

class AmmunitionMergeRequest(BaseModel):
    destination_id: UUID
    expected_source: int = Field(gt=0)
    expected_destination: int = Field(ge=0)
    confirmed: Literal[True]


@router.get("/archive")
async def ammunition_archive(
    request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    lots = db.scalars(select(AmmoLot).options(
        joinedload(AmmoLot.ammo_product).joinedload(AmmoProduct.brand),
        joinedload(AmmoLot.ammo_product).joinedload(AmmoProduct.caliber),
    ).where(AmmoLot.owner_id == current_user.id, AmmoLot.merged_into_lot_id.is_not(None))
      .order_by(AmmoLot.created_at.desc())).all()
    return templates.TemplateResponse(request=request, name="ammunition/archive.html", context={
        "app_name": settings.app_name, "app_version": settings.app_version,
        "current_user": current_user, "is_admin": request.session["user"].get("is_admin", False),
        "lots": lots,
    })


@router.get("/{ammo_lot_id}/merge")
async def ammunition_merge_form(
    ammo_lot_id: UUID, request: Request,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    lot = db.scalar(select(AmmoLot).where(AmmoLot.id == ammo_lot_id, AmmoLot.owner_id == current_user.id))
    if lot is None:
        raise HTTPException(status_code=404, detail="Ammunition lot not found.")
    candidates = merge_candidates(db, source=lot)
    if not candidates:
        raise HTTPException(status_code=409, detail="No eligible destination lots are available.")
    return templates.TemplateResponse(request=request, name="ammunition/merge.html", context={
        "app_name": settings.app_name, "app_version": settings.app_version,
        "current_user": current_user, "is_admin": request.session["user"].get("is_admin", False),
        "lot": lot, "candidates": candidates,
        "source_quantity": get_physical_inventory(db, lot_id=lot.id),
        "balances": {item.id: get_physical_inventory(db, lot_id=item.id) for item in candidates},
        "csrf_token": csrf_token(request),
    })


@router.post("/{ammo_lot_id}/merge")
async def ammunition_merge(
    ammo_lot_id: UUID, payload: AmmunitionMergeRequest, request: Request,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    require_csrf(request)
    try:
        merge = merge_lots(db, owner_id=current_user.id, source_id=ammo_lot_id,
                           destination_id=payload.destination_id,
                           expected_source=payload.expected_source,
                           expected_destination=payload.expected_destination)
    except LookupError:
        raise HTTPException(status_code=404, detail="Ammunition lot not found.")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"success": True, "merge_id": str(merge.id),
            "destination_id": str(merge.destination_lot_id),
            "redirect_url": f"/ammunition/{merge.destination_lot_id}?merged={merge.id}"}


@router.get("/new")
async def ammunition_new(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    calibers = db.scalars(
        select(Caliber)
        .where(Caliber.is_selectable.is_(True))
        .order_by(Caliber.name.asc())
    ).all()

    return templates.TemplateResponse(
        request=request,
        name="ammunition/new.html",
        context={
            "app_name": settings.app_name,
            "app_version": settings.app_version,
            "current_user": current_user,
            "is_admin": request.session["user"].get(
                "is_admin",
                False,
            ),
            "calibers": calibers,
        },
    )

@router.get("/calibers/{caliber_id}")
async def ammunition_caliber_detail(
    caliber_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    caliber = db.scalar(
        select(Caliber)
        .where(Caliber.id == caliber_id)
    )

    if caliber is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Caliber not found.",
        )

    lots = db.scalars(
        select(AmmoLot)
        .join(AmmoLot.ammo_product)
        .join(AmmoProduct.brand)
        .join(AmmoBrand.manufacturer)
        .options(
            joinedload(AmmoLot.ammo_product)
            .joinedload(AmmoProduct.brand)
            .joinedload(AmmoBrand.manufacturer),
            joinedload(AmmoLot.ammo_product)
            .joinedload(AmmoProduct.caliber),
        )
        .where(
            AmmoLot.owner_id == current_user.id,
            AmmoLot.merged_into_lot_id.is_(None),
            AmmoProduct.caliber_id == caliber_id,
        )
        .order_by(
            Organization.name.asc(),
            AmmoProduct.grain_weight.asc().nulls_last(),
            AmmoProduct.projectile_type.asc().nulls_last(),
            AmmoLot.id.asc(),
        )
    ).unique().all()

    if not lots:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No ammunition found for this caliber.",
        )

    inventory_by_lot = {}
    acquired_at_by_lot = {}
    total_quantity = 0
    active_lots = []
    depleted_lots = []

    for lot in lots:
        physical_inventory = get_physical_inventory(
            db,
            lot_id=lot.id,
        )

        inventory_by_lot[lot.id] = physical_inventory
        total_quantity += physical_inventory
        (depleted_lots if physical_inventory == 0 else active_lots).append(lot)

        initial_acquisition = db.scalar(
            select(AmmoInventoryTransaction)
            .where(
                AmmoInventoryTransaction.ammo_lot_id == lot.id,
                AmmoInventoryTransaction.transaction_type
                == AmmoTransactionType.ACQUIRED,
            )
            .order_by(
                AmmoInventoryTransaction.created_at.asc()
            )
            .limit(1)
        )

        acquired_at_by_lot[lot.id] = (
            initial_acquisition.occurred_at
            if initial_acquisition
            else None
        )

    return templates.TemplateResponse(
        request=request,
        name="ammunition/caliber.html",
        context={
            "app_name": settings.app_name,
            "app_version": settings.app_version,
            "current_user": current_user,
            "is_admin": request.session["user"].get(
                "is_admin",
                False,
            ),
            "caliber": caliber,
            "lots": lots,
            "active_groups": _group_lots_by_manufacturer(active_lots),
            "depleted_groups": _group_lots_by_manufacturer(depleted_lots),
            "depleted_lot_count": len(depleted_lots),
            "inventory_by_lot": inventory_by_lot,
            "acquired_at_by_lot": acquired_at_by_lot,
            "total_quantity": total_quantity,
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

    if lot.is_merged:
        raise HTTPException(status_code=409, detail="Merged ammunition lots are read-only.")

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


@router.put("/{ammo_lot_id}/notifications", dependencies=[Depends(require_csrf)])
async def ammunition_notification_settings(
    ammo_lot_id: UUID,
    payload: AmmunitionNotificationSettingsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    lot = db.scalar(
        select(AmmoLot).where(
            AmmoLot.id == ammo_lot_id,
            AmmoLot.owner_id == current_user.id,
        ).with_for_update()
    )
    if lot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ammunition lot not found.")
    if lot.is_merged:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Merged ammunition lots are read-only.")
    if payload.low_inventory_notifications_enabled and payload.low_inventory_threshold is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Enter a positive round threshold when low-inventory alerts are enabled.")
    lot.low_inventory_notifications_enabled = payload.low_inventory_notifications_enabled
    lot.low_inventory_threshold = payload.low_inventory_threshold
    lot.depleted_notifications_enabled = payload.depleted_notifications_enabled
    db.commit()
    return {"success": True}

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

    if lot.is_merged:
        raise HTTPException(status_code=409, detail="Merged ammunition lots are read-only.")

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

    range_usage = db.execute(
        select(
            RangeSession.id.label("session_id"),
            RangeSession.occurred_date,
            RangeSession.location,
            Firearm.id.label("firearm_id"),
            Firearm.model.label("firearm_model"),
            RangeSessionAmmoUsage.quantity,
        )
        .join(
            RangeSessionFirearm,
            RangeSessionFirearm.range_session_id == RangeSession.id,
        )
        .join(
            RangeSessionAmmoUsage,
            RangeSessionAmmoUsage.range_session_firearm_id
            == RangeSessionFirearm.id,
        )
        .join(
            Firearm,
            Firearm.id == RangeSessionFirearm.firearm_id,
        )
        .where(
            RangeSession.owner_id == current_user.id,
            RangeSessionAmmoUsage.ammo_lot_id == lot.id,
        )
        .order_by(
            RangeSession.occurred_date.desc(),
            RangeSession.created_at.desc(),
        )
    ).all()

    merges = db.scalars(select(AmmoLotMerge).where(
        AmmoLotMerge.owner_id == current_user.id,
        or_(AmmoLotMerge.source_lot_id == lot.id, AmmoLotMerge.destination_lot_id == lot.id),
    ).order_by(AmmoLotMerge.created_at)).all()
    candidates = merge_candidates(db, source=lot)
    merge_success = any(str(item.id) == request.query_params.get("merged")
                        and item.destination_lot_id == lot.id for item in merges)

    return templates.TemplateResponse(
        request=request,
        name="ammunition/detail.html",
        context={
            "app_name": settings.app_name,
            "app_version": settings.app_version,
            "current_user": current_user,
            "is_admin": request.session["user"].get("is_admin", False),
            "csrf_token": csrf_token(request),
            "lot": lot,
            "transactions": transactions,
            "expenditure_descriptions": shooting_expenditure_descriptions(
                db, owner_id=current_user.id, transaction_ids=[item.id for item in transactions],
            ),
            "physical_on_hand": physical_on_hand,
            "range_usage": range_usage,
            "merges": merges, "can_merge": bool(candidates),
            "merge_success": merge_success,
        },
    )

@router.post("/")
async def ammunition_acquire(
    payload: AmmunitionAcquisitionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # A known manufacturer lot number identifies a separate physical lot. When
    # absent, offer exact matches before creating anything; this lookup is read-only.
    cleaned_lot_number = (payload.lot_number or "").strip()
    if not cleaned_lot_number and not payload.create_separate_lot:
        matches = find_duplicate_ammunition_lots(
            db,
            owner_id=current_user.id,
            manufacturer_id=payload.manufacturer_id,
            caliber_id=payload.caliber_id,
            grain_weight=payload.grain_weight,
            projectile_type=payload.projectile_type,
        )
        if matches:
            return {
                "success": False,
                "duplicate_suggestions": [
                    {
                        "id": str(lot.id),
                        "brand": lot.ammo_product.brand.name,
                        "caliber": lot.ammo_product.caliber.name,
                        "grain_weight": (
                            str(lot.ammo_product.grain_weight)
                            if lot.ammo_product.grain_weight is not None
                            else None
                        ),
                        "projectile_type": lot.ammo_product.projectile_type,
                        "quantity_on_hand": quantity_on_hand,
                        "created_at": lot.created_at.isoformat(),
                    }
                    for lot, quantity_on_hand in matches
                ],
            }
    try:
        lot = acquire_ammunition(
            db,
            owner_id=current_user.id,
            manufacturer_id=payload.manufacturer_id,
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
