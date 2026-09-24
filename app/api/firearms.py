from datetime import date
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.dependencies import get_current_user, get_db
from app.models.firearm import (
    DatePrecision,
    Firearm,
    FirearmStatus,
    FirearmType,
)
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

from app.models.range_session import RangeSession
from app.models.range_session_firearm import RangeSessionFirearm
from app.models.range_session_ammo_usage import RangeSessionAmmoUsage


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
    manufacture_date: date | None = None
    manufacture_date_precision: DatePrecision = DatePrecision.UNKNOWN
    obtained_date: date | None = None
    obtained_date_precision: DatePrecision = DatePrecision.UNKNOWN
    status: FirearmStatus = FirearmStatus.OWNED
    notes: str | None = None


class FirearmUpdateRequest(BaseModel):
    manufacturer_id: UUID | None = None
    model: str = Field(min_length=1, max_length=255)
    serial_number: str = Field(min_length=1, max_length=255)
    firearm_type: FirearmType
    caliber_id: UUID | None = None
    manufacture_date: date | None = None
    manufacture_date_precision: DatePrecision = DatePrecision.UNKNOWN
    obtained_date: date | None = None
    obtained_date_precision: DatePrecision = DatePrecision.UNKNOWN
    status: FirearmStatus
    notes: str | None = None

def validate_date_precision(
    value: date | None,
    precision: DatePrecision,
    field_name: str,
) -> None:
    if precision == DatePrecision.UNKNOWN:
        if value is not None:
            raise ValueError(
                f"{field_name} must be empty when precision is unknown."
            )
        return

    if value is None:
        raise ValueError(
            f"{field_name} is required when precision is not unknown."
        )

    if precision in {
        DatePrecision.YEAR,
        DatePrecision.APPROXIMATE_YEAR,
    }:
        if value.month != 1 or value.day != 1:
            raise ValueError(
                f"{field_name} must use January 1 for year-only precision."
            )

    if precision == DatePrecision.MONTH and value.day != 1:
        raise ValueError(
            f"{field_name} must use the first day of the month "
            "for month precision."
        )

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
            "firearm_statuses": list(FirearmStatus),
            "date_precisions": list(DatePrecision),
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

    try:
        validate_date_precision(
            payload.manufacture_date,
            payload.manufacture_date_precision,
            "Manufacture Date",
        )
        validate_date_precision(
            payload.obtained_date,
            payload.obtained_date_precision,
            "Obtained Date",
        )
    except ValueError as exc:
        return {
            "success": False,
            "error": str(exc),
        }

    notes = None
    if payload.notes is not None:
        notes = payload.notes.strip() or None

    firearm = Firearm(
        owner_id=current_user.id,
        manufacturer_id=manufacturer.id if manufacturer else None,
        caliber_id=caliber.id if caliber else None,
        model=model,
        serial_number=serial_number,
        firearm_type=payload.firearm_type,
        manufacture_date=payload.manufacture_date,
        manufacture_date_precision=payload.manufacture_date_precision,
        obtained_date=payload.obtained_date,
        obtained_date_precision=payload.obtained_date_precision,
        status=payload.status,
        notes=notes,
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

    try:
        validate_date_precision(
            payload.manufacture_date,
            payload.manufacture_date_precision,
            "Manufacture Date",
        )
        validate_date_precision(
            payload.obtained_date,
            payload.obtained_date_precision,
            "Obtained Date",
        )
    except ValueError as exc:
        return {
            "success": False,
            "error": str(exc),
        }

    notes = None
    if payload.notes is not None:
        notes = payload.notes.strip() or None

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

    if (
        firearm.manufacture_date != payload.manufacture_date
        or firearm.manufacture_date_precision
        != payload.manufacture_date_precision
    ):
        changes["manufacture_date"] = {
            "old": {
                "date": (
                    firearm.manufacture_date.isoformat()
                    if firearm.manufacture_date
                    else None
                ),
                "precision": firearm.manufacture_date_precision.value,
            },
            "new": {
                "date": (
                    payload.manufacture_date.isoformat()
                    if payload.manufacture_date
                    else None
                ),
                "precision": payload.manufacture_date_precision.value,
            },
        }

    if (
        firearm.obtained_date != payload.obtained_date
        or firearm.obtained_date_precision
        != payload.obtained_date_precision
    ):
        changes["obtained_date"] = {
            "old": {
                "date": (
                    firearm.obtained_date.isoformat()
                    if firearm.obtained_date
                    else None
                ),
                "precision": firearm.obtained_date_precision.value,
            },
            "new": {
                "date": (
                    payload.obtained_date.isoformat()
                    if payload.obtained_date
                    else None
                ),
                "precision": payload.obtained_date_precision.value,
            },
        }

    if firearm.status != payload.status:
        changes["status"] = {
            "old": firearm.status.value,
            "new": payload.status.value,
        }

    if firearm.notes != notes:
        changes["notes"] = {
            "old": firearm.notes,
            "new": notes,
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

    firearm.manufacture_date = payload.manufacture_date
    firearm.manufacture_date_precision = (
        payload.manufacture_date_precision
    )
    firearm.obtained_date = payload.obtained_date
    firearm.obtained_date_precision = (
        payload.obtained_date_precision
    )
    firearm.status = payload.status
    firearm.notes = notes

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
            "firearm_statuses": list(FirearmStatus),
            "date_precisions": list(DatePrecision),
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

    range_history = db.execute(
        select(
            RangeSession.id.label("session_id"),
            RangeSession.occurred_date,
            RangeSession.location,
            func.coalesce(
                func.sum(RangeSessionAmmoUsage.quantity),
                0,
            ).label("rounds_fired"),
        )
        .join(
            RangeSessionFirearm,
            RangeSessionFirearm.range_session_id == RangeSession.id,
        )
        .outerjoin(
            RangeSessionAmmoUsage,
            RangeSessionAmmoUsage.range_session_firearm_id
            == RangeSessionFirearm.id,
        )
        .where(
            RangeSession.owner_id == current_user.id,
            RangeSessionFirearm.firearm_id == firearm.id,
        )
        .group_by(
            RangeSession.id,
            RangeSession.occurred_date,
            RangeSession.location,
        )
        .order_by(
            RangeSession.occurred_date.desc(),
            RangeSession.created_at.desc(),
        )
    ).all()

    return templates.TemplateResponse(
        request=request,
        name="firearms/detail.html",
        context={
            "app_name": settings.app_name,
            "app_version": settings.app_version,
            "current_user": current_user,
            "is_admin": request.session["user"].get("is_admin", False),
            "firearm": firearm,
            "range_history": range_history,
        },
    )