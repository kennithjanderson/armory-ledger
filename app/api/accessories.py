from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.core.dependencies import get_current_user, get_db
from app.main_templates import templates
from app.models.accessory import Accessory
from app.models.firearm import Firearm
from app.models.organization import ManufacturerProfile, Organization
from app.models.user import User
from app.services.accessory_service import (
    create_accessory,
    get_accessory,
    update_accessory,
)
from app.services.manufacturer_service import (
    create_manufacturer,
    find_exact_manufacturer,
    find_similar_manufacturers,
)


router = APIRouter(
    prefix="/accessories",
    tags=["accessories"],
)


class ManufacturerCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class AccessoryCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    manufacturer_id: UUID | None = None
    model: str | None = Field(default=None, max_length=255)
    serial_number: str | None = Field(default=None, max_length=255)
    purchase_date: date | None = None
    purchase_location: str | None = Field(default=None, max_length=255)
    firearm_id: UUID | None = None
    storage_location: str | None = Field(default=None, max_length=255)
    notes: str | None = None


class AccessoryUpdateRequest(AccessoryCreateRequest):
    pass


def _template_context(
    request: Request,
    current_user: User,
    **extra,
):
    return {
        "app_name": settings.app_name,
        "app_version": settings.app_version,
        "current_user": current_user,
        "is_admin": request.session["user"].get("is_admin", False),
        **extra,
    }


def _get_selectable_manufacturer(
    db: Session,
    manufacturer_id: UUID | None,
) -> Organization | None:
    if manufacturer_id is None:
        return None

    return db.scalar(
        select(Organization)
        .join(
            ManufacturerProfile,
            ManufacturerProfile.organization_id == Organization.id,
        )
        .where(
            Organization.id == manufacturer_id,
            ManufacturerProfile.is_selectable.is_(True),
        )
    )


@router.get("/")
async def accessory_list(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    accessories = db.scalars(
        select(Accessory)
        .options(
            joinedload(Accessory.manufacturer),
            joinedload(Accessory.firearm),
        )
        .where(Accessory.owner_id == current_user.id)
        .order_by(Accessory.created_at.desc())
    ).all()

    return templates.TemplateResponse(
        request=request,
        name="accessories/list.html",
        context=_template_context(
            request,
            current_user,
            accessories=accessories,
        ),
    )


@router.get("/new")
async def accessory_new(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    firearms = db.scalars(
        select(Firearm)
        .where(Firearm.owner_id == current_user.id)
        .order_by(Firearm.model.asc())
    ).all()

    return templates.TemplateResponse(
        request=request,
        name="accessories/new.html",
        context=_template_context(
            request,
            current_user,
            firearms=firearms,
        ),
    )


@router.get("/manufacturer-search")
async def manufacturer_search(
    q: str = Query(default="", max_length=255),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    search_term = " ".join(q.strip().split())

    if not search_term:
        return {
            "query": "",
            "match_type": "empty",
            "exact": None,
            "similar": [],
        }

    exact = find_exact_manufacturer(db, search_term)

    if exact is not None:
        return {
            "query": search_term,
            "match_type": "exact",
            "exact": {
                "id": str(exact.id),
                "name": exact.name,
            },
            "similar": [],
        }

    similar = find_similar_manufacturers(
        db,
        search_term,
    )

    return {
        "query": search_term,
        "match_type": "similar" if similar else "none",
        "exact": None,
        "similar": [
            {
                "id": str(organization.id),
                "name": organization.name,
                "score": round(score, 3),
            }
            for organization, score in similar
        ],
    }


@router.post(
    "/manufacturers",
    status_code=status.HTTP_201_CREATED,
)
async def manufacturer_create(
    payload: ManufacturerCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        manufacturer = create_manufacturer(
            db,
            payload.name,
        )
    except ValueError as exc:
        return {
            "success": False,
            "error": str(exc),
        }

    return {
        "success": True,
        "manufacturer": {
            "id": str(manufacturer.id),
            "name": manufacturer.name,
        },
    }


@router.post("/", status_code=status.HTTP_201_CREATED)
async def accessory_create(
    payload: AccessoryCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.manufacturer_id is not None:
        manufacturer = _get_selectable_manufacturer(
            db,
            payload.manufacturer_id,
        )

        if manufacturer is None:
            return {
                "success": False,
                "error": "Selected manufacturer is invalid.",
            }

    try:
        accessory = create_accessory(
            db,
            owner_id=current_user.id,
            name=payload.name,
            manufacturer_id=payload.manufacturer_id,
            model=payload.model,
            serial_number=payload.serial_number,
            purchase_date=payload.purchase_date,
            purchase_location=payload.purchase_location,
            firearm_id=payload.firearm_id,
            storage_location=payload.storage_location,
            notes=payload.notes,
        )
    except (ValueError, LookupError) as exc:
        return {
            "success": False,
            "error": str(exc),
        }

    return {
        "success": True,
        "accessory": {
            "id": str(accessory.id),
        },
    }


@router.put("/{accessory_id}")
async def accessory_update(
    accessory_id: UUID,
    payload: AccessoryUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.manufacturer_id is not None:
        manufacturer = _get_selectable_manufacturer(
            db,
            payload.manufacturer_id,
        )

        if manufacturer is None:
            return {
                "success": False,
                "error": "Selected manufacturer is invalid.",
            }

    try:
        accessory = update_accessory(
            db,
            owner_id=current_user.id,
            actor_user_id=current_user.id,
            accessory_id=accessory_id,
            name=payload.name,
            manufacturer_id=payload.manufacturer_id,
            model=payload.model,
            serial_number=payload.serial_number,
            purchase_date=payload.purchase_date,
            purchase_location=payload.purchase_location,
            firearm_id=payload.firearm_id,
            storage_location=payload.storage_location,
            notes=payload.notes,
        )
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Accessory not found.",
        )
    except ValueError as exc:
        return {
            "success": False,
            "error": str(exc),
        }

    return {
        "success": True,
        "accessory": {
            "id": str(accessory.id),
        },
    }


@router.get("/{accessory_id}/edit")
async def accessory_edit(
    accessory_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        accessory = get_accessory(
            db,
            owner_id=current_user.id,
            accessory_id=accessory_id,
        )
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Accessory not found.",
        )

    firearms = db.scalars(
        select(Firearm)
        .where(Firearm.owner_id == current_user.id)
        .order_by(Firearm.model.asc())
    ).all()

    return templates.TemplateResponse(
        request=request,
        name="accessories/edit.html",
        context=_template_context(
            request,
            current_user,
            accessory=accessory,
            firearms=firearms,
        ),
    )


@router.get("/{accessory_id}")
async def accessory_detail(
    accessory_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        accessory = get_accessory(
            db,
            owner_id=current_user.id,
            accessory_id=accessory_id,
        )
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Accessory not found.",
        )

    return templates.TemplateResponse(
        request=request,
        name="accessories/detail.html",
        context=_template_context(
            request,
            current_user,
            accessory=accessory,
        ),
    )
