from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.dependencies import get_current_user, get_db
from app.models.firearm import Firearm, FirearmType
from app.models.user import User
from app.main_templates import templates

from app.models.audit_event import AuditEvent

from app.models.caliber import Caliber

from app.models.organization import Organization, ManufacturerProfile

from app.services.manufacturer_service import (
    find_exact_manufacturer,
    find_similar_manufacturers,
    create_manufacturer,
)


router = APIRouter(
    prefix="/firearms",
    tags=["firearms"],
)

class ManufacturerCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)

class FirearmCreateRequest(BaseModel):
    manufacturer_id: UUID | None = None
    model: str = Field(min_length=1, max_length=255)
    serial_number: str = Field(min_length=1, max_length=255)
    firearm_type: FirearmType
    caliber_id: UUID | None = None

class FirearmUpdateRequest(BaseModel):
    manufacturer_id: UUID | None = None
    model: str = Field(min_length=1, max_length=255)
    serial_number: str = Field(min_length=1, max_length=255)
    firearm_type: FirearmType
    caliber_id: UUID | None = None

@router.get("/")
async def firearm_list(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    firearms = db.scalars(
        select(Firearm)
        .where(Firearm.owner_id == current_user.id)
        .order_by(Firearm.created_at.desc())
    ).all()

    return templates.TemplateResponse(
        request=request,
        name="firearms/list.html",
        context={
            "app_name": settings.app_name,
            "app_version": settings.app_version,
            "current_user": current_user,
            "is_admin": request.session["user"].get("is_admin", False),
            "firearms": firearms,
        },
    )

@router.get("/new")
async def firearm_new(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    calibers = db.scalars(
        select(Caliber)
        .where(Caliber.is_selectable.is_(True))
        .order_by(Caliber.name)
    ).all()

    return templates.TemplateResponse(
        request=request,
        name="firearms/new.html",
        context={
            "app_name": settings.app_name,
            "app_version": settings.app_version,
            "current_user": current_user,
            "is_admin": request.session["user"].get("is_admin", False),
            "calibers": calibers,
            "firearm_types": list(FirearmType),
        },
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

@router.post("/manufacturers", status_code=status.HTTP_201_CREATED)
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
async def firearm_create(
    payload: FirearmCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    manufacturer = None

    if payload.manufacturer_id is not None:
        manufacturer = db.scalar(
            select(Organization)
            .join(
                ManufacturerProfile,
                ManufacturerProfile.organization_id == Organization.id,
            )
            .where(
                Organization.id == payload.manufacturer_id,
                ManufacturerProfile.is_selectable.is_(True),
            )
        )

        if manufacturer is None:
            return {
                "success": False,
                "error": "Selected manufacturer is invalid.",
            }

    caliber = None

    if payload.caliber_id is not None:
        caliber = db.scalar(
            select(Caliber).where(
                Caliber.id == payload.caliber_id,
                Caliber.is_selectable.is_(True),
            )
        )

        if caliber is None:
            return {
                "success": False,
                "error": "Selected caliber is invalid.",
            }

    model = " ".join(payload.model.strip().split())
    serial_number = payload.serial_number.strip()

    if not model:
        return {
            "success": False,
            "error": "Model is required.",
        }

    if not serial_number:
        return {
            "success": False,
            "error": "Serial number is required.",
        }

    firearm = Firearm(
        owner_id=current_user.id,
        manufacturer_id=manufacturer.id if manufacturer else None,
        caliber_id=caliber.id if caliber else None,
        model=model,
        serial_number=serial_number,
        firearm_type=payload.firearm_type,
    )

    db.add(firearm)
    db.commit()
    db.refresh(firearm)

    return {
        "success": True,
        "firearm": {
            "id": str(firearm.id),
        },
    }

@router.put("/{firearm_id}")
async def firearm_update(
    firearm_id: UUID,
    payload: FirearmUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    firearm = db.scalar(
        select(Firearm).where(
            Firearm.id == firearm_id,
            Firearm.owner_id == current_user.id,
        )
    )

    if firearm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Firearm not found.",
        )

    manufacturer = None

    if payload.manufacturer_id is not None:
        manufacturer = db.scalar(
            select(Organization)
            .join(
                ManufacturerProfile,
                ManufacturerProfile.organization_id == Organization.id,
            )
            .where(
                Organization.id == payload.manufacturer_id,
                ManufacturerProfile.is_selectable.is_(True),
            )
        )

        if manufacturer is None:
            return {
                "success": False,
                "error": "Selected manufacturer is invalid.",
            }

    caliber = None

    if payload.caliber_id is not None:
        caliber = db.scalar(
            select(Caliber).where(
                Caliber.id == payload.caliber_id,
                Caliber.is_selectable.is_(True),
            )
        )

        if caliber is None:
            return {
                "success": False,
                "error": "Selected caliber is invalid.",
            }

    model = " ".join(payload.model.strip().split())
    serial_number = payload.serial_number.strip()

    if not model:
        return {
            "success": False,
            "error": "Model is required.",
        }

    if not serial_number:
        return {
            "success": False,
            "error": "Serial number is required.",
        }

    changes = {}

    if firearm.manufacturer_id != payload.manufacturer_id:
        changes["manufacturer"] = {
            "old": {
                "id": str(firearm.manufacturer_id)
                if firearm.manufacturer_id
                else None,
                "name": firearm.manufacturer.name
                if firearm.manufacturer
                else None,
            },
            "new": {
                "id": str(manufacturer.id)
                if manufacturer
                else None,
                "name": manufacturer.name
                if manufacturer
                else None,
            },
        }

    if firearm.model != model:
        changes["model"] = {
            "old": firearm.model,
            "new": model,
        }

    if firearm.serial_number != serial_number:
        changes["serial_number"] = {
            "old": firearm.serial_number,
            "new": serial_number,
        }

    if firearm.firearm_type != payload.firearm_type:
        changes["firearm_type"] = {
            "old": firearm.firearm_type.value,
            "new": payload.firearm_type.value,
        }

    if firearm.caliber_id != payload.caliber_id:
        changes["caliber"] = {
            "old": {
                "id": str(firearm.caliber_id)
                if firearm.caliber_id
                else None,
                "name": firearm.caliber.name
                if firearm.caliber
                else None,
            },
            "new": {
                "id": str(caliber.id)
                if caliber
                else None,
                "name": caliber.name
                if caliber
                else None,
            },
        }

    if not changes:
        return {
            "success": True,
            "changed": False,
            "firearm": {
                "id": str(firearm.id),
            },
        }

    firearm.manufacturer_id = (
        manufacturer.id if manufacturer else None
    )
    firearm.model = model
    firearm.serial_number = serial_number
    firearm.firearm_type = payload.firearm_type
    firearm.caliber_id = (
        caliber.id if caliber else None
    )

    audit_event = AuditEvent(
        owner_id=firearm.owner_id,
        actor_user_id=current_user.id,
        entity_type="firearm",
        entity_id=firearm.id,
        action="updated",
        changes=changes,
    )

    db.add(audit_event)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(firearm)

    return {
        "success": True,
        "changed": True,
        "firearm": {
            "id": str(firearm.id),
        },
    }

@router.get("/{firearm_id}/edit")
async def firearm_edit(
    firearm_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    firearm = db.scalar(
        select(Firearm).where(
            Firearm.id == firearm_id,
            Firearm.owner_id == current_user.id,
        )
    )

    if firearm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Firearm not found.",
        )

    calibers = db.scalars(
        select(Caliber)
        .where(Caliber.is_selectable.is_(True))
        .order_by(Caliber.name)
    ).all()

    return templates.TemplateResponse(
        request=request,
        name="firearms/edit.html",
        context={
            "app_name": settings.app_name,
            "app_version": settings.app_version,
            "current_user": current_user,
            "is_admin": request.session["user"].get("is_admin", False),
            "firearm": firearm,
            "calibers": calibers,
            "firearm_types": list(FirearmType),
        },
    )

@router.get("/{firearm_id}")
async def firearm_detail(
    firearm_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    firearm = db.scalar(
        select(Firearm).where(
            Firearm.id == firearm_id,
            Firearm.owner_id == current_user.id,
        )
    )

    if firearm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Firearm not found.",
        )

    return templates.TemplateResponse(
        request=request,
        name="firearms/detail.html",
        context={
            "app_name": settings.app_name,
            "app_version": settings.app_version,
            "current_user": current_user,
            "is_admin": request.session["user"].get("is_admin", False),
            "firearm": firearm,
        },
    )