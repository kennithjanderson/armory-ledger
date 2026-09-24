from datetime import date
from uuid import UUID
from fastapi import APIRouter, Depends, Request, status, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.core.dependencies import get_current_user, get_db
from app.main_templates import templates
from app.models.ammo_lot import AmmoLot
from app.models.ammo_product import AmmoProduct
from app.models.firearm import Firearm, FirearmStatus
from app.models.range_session import RangeSession
from app.models.range_session_firearm import RangeSessionFirearm
from app.models.range_session_ammo_usage import RangeSessionAmmoUsage
from app.models.user import User
from app.services.ammo_inventory_service import get_physical_inventory

from pydantic import BaseModel, Field

from app.models.range_session_ammo_usage import RangeAmmoSourceType

from app.services.range_service import (
    RangeAmmoUsageInput,
    RangeFirearmInput,
    create_range_session,
    update_range_session,
)



router = APIRouter(
    prefix="/range",
    tags=["range"],
)

class RangeAmmoUsageRequest(BaseModel):
    range_session_ammo_usage_id: UUID | None = None
    source_type: RangeAmmoSourceType
    quantity: int = Field(gt=0)
    ammo_lot_id: UUID | None = None
    description: str | None = Field(default=None, max_length=255)


class RangeFirearmRequest(BaseModel):
    range_session_firearm_id: UUID | None = None
    firearm_id: UUID
    notes: str | None = None
    ammo_usage: list[RangeAmmoUsageRequest] = Field(min_length=1)


class RangeSessionCreateRequest(BaseModel):
    occurred_date: date
    location: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    firearms: list[RangeFirearmRequest] = Field(min_length=1)


@router.get("/")
async def range_list(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sessions = db.scalars(
        select(RangeSession)
        .where(RangeSession.owner_id == current_user.id)
        .order_by(
            RangeSession.occurred_date.desc(),
            RangeSession.created_at.desc(),
        )
    ).all()

    return templates.TemplateResponse(
        request=request,
        name="range/list.html",
        context={
            "app_name": settings.app_name,
            "app_version": settings.app_version,
            "current_user": current_user,
            "is_admin": request.session["user"].get(
                "is_admin",
                False,
            ),
            "sessions": sessions,
        },
    )


@router.get("/new")
async def range_new(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    firearms = db.scalars(
        select(Firearm)
        .options(
            joinedload(Firearm.manufacturer),
        )
        .where(
            Firearm.owner_id == current_user.id,
            Firearm.status == FirearmStatus.OWNED,
        )
        .order_by(
            Firearm.model.asc(),
            Firearm.id.asc(),
        )
    ).unique().all()

    ammo_lots = db.scalars(
        select(AmmoLot)
        .join(AmmoLot.ammo_product)
        .options(
            joinedload(AmmoLot.ammo_product)
            .joinedload(AmmoProduct.brand),
            joinedload(AmmoLot.ammo_product)
            .joinedload(AmmoProduct.caliber),
        )
        .where(AmmoLot.owner_id == current_user.id)
        .order_by(
            AmmoProduct.grain_weight.asc().nulls_last(),
            AmmoLot.id.asc(),
        )
    ).unique().all()

    inventory_by_lot = {
        lot.id: get_physical_inventory(
            db,
            lot_id=lot.id,
        )
        for lot in ammo_lots
    }

    ammo_lots = [
        lot
        for lot in ammo_lots
        if inventory_by_lot.get(lot.id, 0) > 0
    ]

    return templates.TemplateResponse(
        request=request,
        name="range/new.html",
        context={
            "app_name": settings.app_name,
            "app_version": settings.app_version,
            "current_user": current_user,
            "is_admin": request.session["user"].get(
                "is_admin",
                False,
            ),
            "firearms": firearms,
            "ammo_lots": ammo_lots,
            "inventory_by_lot": inventory_by_lot,
            "edit_mode": False,
            "initial_data": None,
        },
    )

@router.post("/", status_code=status.HTTP_201_CREATED)
async def range_create(
    payload: RangeSessionCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    firearms = [
        RangeFirearmInput(
            firearm_id=firearm.firearm_id,
            notes=firearm.notes,
            ammo_usage=[
                RangeAmmoUsageInput(
                    source_type=ammo.source_type,
                    quantity=ammo.quantity,
                    ammo_lot_id=ammo.ammo_lot_id,
                    description=ammo.description,
                )
                for ammo in firearm.ammo_usage
            ],
        )
        for firearm in payload.firearms
    ]

    try:
        range_session = create_range_session(
            db,
            owner_id=current_user.id,
            actor_user_id=current_user.id,
            occurred_date=payload.occurred_date,
            location=payload.location,
            notes=payload.notes,
            firearms=firearms,
        )

    except (ValueError, LookupError) as exc:
        return {
            "success": False,
            "error": str(exc),
        }

    return {
        "success": True,
        "range_session": {
            "id": str(range_session.id),
        },
    }

@router.get("/{session_id}/edit")
async def range_edit(
    session_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    range_session = db.scalar(
        select(RangeSession).where(
            RangeSession.id == session_id,
            RangeSession.owner_id == current_user.id,
        )
    )

    if range_session is None:
        raise HTTPException(
            status_code=404,
            detail="Range session not found.",
        )

    session_firearms = db.scalars(
        select(RangeSessionFirearm)
        .where(
            RangeSessionFirearm.range_session_id
            == range_session.id
        )
        .order_by(
            RangeSessionFirearm.created_at.asc(),
            RangeSessionFirearm.id.asc(),
        )
    ).all()

    existing_firearm_ids = {
        item.firearm_id
        for item in session_firearms
    }

    #
    # Normally the Range form only shows firearms currently owned.
    #
    # Edit is different: a firearm already referenced by this
    # session must remain selectable even if its current status
    # has since changed.
    #
    firearms = db.scalars(
        select(Firearm)
        .options(
            joinedload(Firearm.manufacturer),
        )
        .where(
            Firearm.owner_id == current_user.id,
            or_(
                Firearm.status == FirearmStatus.OWNED,
                Firearm.id.in_(existing_firearm_ids),
            ),
        )
        .order_by(
            Firearm.model.asc(),
            Firearm.id.asc(),
        )
    ).unique().all()

    session_firearm_ids = [
        item.id
        for item in session_firearms
    ]

    if session_firearm_ids:
        existing_usage = db.scalars(
            select(RangeSessionAmmoUsage)
            .where(
                RangeSessionAmmoUsage.range_session_firearm_id.in_(
                    session_firearm_ids
                )
            )
            .order_by(
                RangeSessionAmmoUsage.created_at.asc(),
                RangeSessionAmmoUsage.id.asc(),
            )
        ).all()
    else:
        existing_usage = []

    usage_by_firearm: dict[UUID, list[RangeSessionAmmoUsage]] = {}

    for usage in existing_usage:
        usage_by_firearm.setdefault(
            usage.range_session_firearm_id,
            [],
        ).append(usage)

    #
    # Normally the Range form only shows ammo currently on hand.
    #
    # Edit is different: a lot already referenced by this session
    # must remain selectable even if its current physical balance
    # has reached zero.
    #
    referenced_lot_ids = {
        usage.ammo_lot_id
        for usage in existing_usage
        if usage.ammo_lot_id is not None
    }

    all_ammo_lots = db.scalars(
        select(AmmoLot)
        .join(AmmoLot.ammo_product)
        .options(
            joinedload(AmmoLot.ammo_product)
            .joinedload(AmmoProduct.brand),

            joinedload(AmmoLot.ammo_product)
            .joinedload(AmmoProduct.caliber),
        )
        .where(AmmoLot.owner_id == current_user.id)
        .order_by(
            AmmoProduct.grain_weight.asc().nulls_last(),
            AmmoLot.id.asc(),
        )
    ).unique().all()

    inventory_by_lot = {
        lot.id: get_physical_inventory(
            db,
            lot_id=lot.id,
        )
        for lot in all_ammo_lots
    }

    ammo_lots = [
        lot
        for lot in all_ammo_lots
        if (
            inventory_by_lot.get(lot.id, 0) > 0
            or lot.id in referenced_lot_ids
        )
    ]

    initial_firearms = []

    for session_firearm in session_firearms:
        ammo_usage = []

        for usage in usage_by_firearm.get(
            session_firearm.id,
            [],
        ):
            ammo_usage.append(
                {
                    "range_session_ammo_usage_id": str(
                        usage.id
                    ),
                    "source_type": usage.source_type.value,
                    "quantity": usage.quantity,
                    "ammo_lot_id": (
                        str(usage.ammo_lot_id)
                        if usage.ammo_lot_id
                        else None
                    ),
                    "description": usage.description,
                }
            )

        initial_firearms.append(
            {
                "range_session_firearm_id": str(
                    session_firearm.id
                ),
                "firearm_id": str(
                    session_firearm.firearm_id
                ),
                "notes": session_firearm.notes,
                "ammo_usage": ammo_usage,
            }
        )

    initial_data = {
        "range_session_id": str(range_session.id),
        "occurred_date": (
            range_session.occurred_date.isoformat()
        ),
        "location": range_session.location,
        "notes": range_session.notes,
        "firearms": initial_firearms,
    }

    return templates.TemplateResponse(
        request=request,
        name="range/new.html",
        context={
            "app_name": settings.app_name,
            "app_version": settings.app_version,
            "current_user": current_user,
            "is_admin": request.session["user"].get(
                "is_admin",
                False,
            ),
            "firearms": firearms,
            "ammo_lots": ammo_lots,
            "inventory_by_lot": inventory_by_lot,

            # Edit-specific context
            "edit_mode": True,
            "range_session": range_session,
            "initial_data": initial_data,
        },
    )

@router.get("/{session_id}")
async def range_detail(
    session_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    range_session = db.scalar(
        select(RangeSession)
        .where(
            RangeSession.id == session_id,
            RangeSession.owner_id == current_user.id,
        )
    )

    if range_session is None:
        raise HTTPException(
            status_code=404,
            detail="Range session not found.",
        )

    session_firearms = db.scalars(
        select(RangeSessionFirearm)
        .where(
            RangeSessionFirearm.range_session_id
            == range_session.id
        )
        .options(
            joinedload(RangeSessionFirearm.firearm)
            .joinedload(Firearm.manufacturer)
        )
        .order_by(
            RangeSessionFirearm.created_at.asc(),
            RangeSessionFirearm.id.asc(),
        )
    ).unique().all()

    firearm_records = []

    total_rounds = 0

    for session_firearm in session_firearms:
        ammo_usage = db.scalars(
            select(RangeSessionAmmoUsage)
            .where(
                RangeSessionAmmoUsage.range_session_firearm_id
                == session_firearm.id
            )
            .options(
                joinedload(RangeSessionAmmoUsage.ammo_lot)
                .joinedload(AmmoLot.ammo_product)
                .joinedload(AmmoProduct.brand),

                joinedload(RangeSessionAmmoUsage.ammo_lot)
                .joinedload(AmmoLot.ammo_product)
                .joinedload(AmmoProduct.caliber),

                joinedload(
                    RangeSessionAmmoUsage.inventory_transaction
                ),
            )
            .order_by(
                RangeSessionAmmoUsage.created_at.asc(),
                RangeSessionAmmoUsage.id.asc(),
            )
        ).unique().all()

        firearm_rounds = sum(
            usage.quantity
            for usage in ammo_usage
        )

        total_rounds += firearm_rounds

        firearm_records.append(
            {
                "session_firearm": session_firearm,
                "ammo_usage": ammo_usage,
                "rounds": firearm_rounds,
            }
        )

    return templates.TemplateResponse(
        request=request,
        name="range/detail.html",
        context={
            "app_name": settings.app_name,
            "app_version": settings.app_version,
            "current_user": current_user,
            "is_admin": request.session["user"].get(
                "is_admin",
                False,
            ),
            "range_session": range_session,
            "firearm_records": firearm_records,
            "total_rounds": total_rounds,
        },
    )

@router.put("/{session_id}")
async def range_update(
    session_id: UUID,
    payload: RangeSessionCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    firearms = [
        RangeFirearmInput(
            range_session_firearm_id=(
                firearm.range_session_firearm_id
            ),
            firearm_id=firearm.firearm_id,
            notes=firearm.notes,
            ammo_usage=[
                RangeAmmoUsageInput(
                    range_session_ammo_usage_id=(
                        ammo.range_session_ammo_usage_id
                    ),
                    source_type=ammo.source_type,
                    quantity=ammo.quantity,
                    ammo_lot_id=ammo.ammo_lot_id,
                    description=ammo.description,
                )
                for ammo in firearm.ammo_usage
            ],
        )
        for firearm in payload.firearms
    ]

    try:
        range_session = update_range_session(
            db,
            range_session_id=session_id,
            owner_id=current_user.id,
            actor_user_id=current_user.id,
            occurred_date=payload.occurred_date,
            location=payload.location,
            notes=payload.notes,
            firearms=firearms,
        )

    except (ValueError, LookupError) as exc:
        return {
            "success": False,
            "error": str(exc),
        }

    return {
        "success": True,
        "range_session": {
            "id": str(range_session.id),
        },
    }