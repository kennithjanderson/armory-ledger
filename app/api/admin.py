from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.csrf import csrf_token, require_csrf
from app.core.dependencies import get_db, require_admin
from app.main_templates import templates
from app.models.announcement import Announcement
from app.models.caliber import Caliber
from app.models.caliber_alias import CaliberAlias
from app.models.caliber_alias_audit_event import CaliberAliasAuditEvent
from app.models.organization import ManufacturerProfile, Organization
from app.models.organization_alias import OrganizationAlias
from app.models.manufacturer_alias_audit_event import ManufacturerAliasAuditEvent
from app.models.user import User
from app.schemas.announcement import AnnouncementRequest
from app.schemas.announcement_schedule import SchedulePreview
from app.services.announcement_service import save_announcement
from app.services.manufacturer_service import (
    add_manufacturer_alias,
    delete_manufacturer_alias,
)
from app.services.caliber_service import add_caliber_alias, delete_caliber_alias


router = APIRouter(prefix="/admin", tags=["administration"], dependencies=[Depends(require_admin)])


class ManufacturerAliasRequest(BaseModel):
    alias: str = Field(min_length=1, max_length=255)


class CaliberAliasRequest(BaseModel):
    alias: str = Field(min_length=1, max_length=100)


def render(request, current_user, template, **context):
    response = templates.TemplateResponse(
        request=request, name=template,
        context={
            "app_name": settings.app_name, "app_version": settings.app_version,
            "current_user": current_user, "is_admin": True,
            "csrf_token": csrf_token(request), **context,
        },
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("")
def index(request: Request, current_user: User = Depends(require_admin)):
    return render(request, current_user, "admin/index.html")


@router.get("/users")
def users(request: Request, current_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    # Explicit account-only projection: never join inventory or return ORM users.
    accounts = db.execute(select(
        User.display_name, User.email, User.id, User.created_at, User.last_login_at,
    ).order_by(User.display_name, User.id)).mappings().all()
    return render(request, current_user, "admin/users.html", accounts=accounts)


@router.get("/manufacturers")
def manufacturers(request: Request, current_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    records = db.execute(select(
        Organization.id, Organization.name, Organization.legal_name,
        Organization.status, ManufacturerProfile.is_selectable,
    ).join(ManufacturerProfile).order_by(Organization.name, Organization.id)).mappings().all()
    return render(request, current_user, "admin/manufacturers.html", records=records)


def get_manufacturer(db: Session, manufacturer_id: UUID) -> Organization:
    manufacturer = db.scalar(
        select(Organization)
        .join(ManufacturerProfile, ManufacturerProfile.organization_id == Organization.id)
        .where(Organization.id == manufacturer_id)
    )
    if manufacturer is None:
        raise HTTPException(status_code=404, detail="Manufacturer not found.")
    return manufacturer


@router.get("/manufacturers/{manufacturer_id}/aliases")
def manufacturer_aliases(
    manufacturer_id: UUID, request: Request,
    current_user: User = Depends(require_admin), db: Session = Depends(get_db),
):
    manufacturer = get_manufacturer(db, manufacturer_id)
    aliases = db.scalars(
        select(OrganizationAlias).where(
            OrganizationAlias.organization_id == manufacturer.id,
        ).order_by(OrganizationAlias.alias, OrganizationAlias.id)
    ).all()
    changes = db.execute(
        select(ManufacturerAliasAuditEvent, User.display_name, User.email)
        .join(User, User.id == ManufacturerAliasAuditEvent.actor_user_id)
        .where(ManufacturerAliasAuditEvent.manufacturer_id == manufacturer.id)
        .order_by(ManufacturerAliasAuditEvent.created_at.desc(), ManufacturerAliasAuditEvent.id)
        .limit(50)
    ).all()
    return render(
        request, current_user, "admin/manufacturer_aliases.html",
        manufacturer=manufacturer, aliases=aliases, changes=changes,
    )


@router.post(
    "/manufacturers/{manufacturer_id}/aliases",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def manufacturer_alias_create(
    manufacturer_id: UUID, payload: ManufacturerAliasRequest,
    current_user: User = Depends(require_admin), db: Session = Depends(get_db),
):
    get_manufacturer(db, manufacturer_id)
    try:
        alias = add_manufacturer_alias(
            db, manufacturer_id, payload.alias, actor_user_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Alias conflicts with an existing manufacturer name or alias.") from exc
    return {"success": True, "id": str(alias.id), "alias": alias.alias}


@router.delete(
    "/manufacturers/{manufacturer_id}/aliases/{alias_id}",
    dependencies=[Depends(require_csrf)],
)
def manufacturer_alias_delete(
    manufacturer_id: UUID, alias_id: UUID, current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    get_manufacturer(db, manufacturer_id)
    try:
        delete_manufacturer_alias(
            db, organization_id=manufacturer_id, alias_id=alias_id,
            actor_user_id=current_user.id,
        )
    except ValueError as exc:
        status_code = 404 if str(exc) == "Manufacturer alias not found." else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return {"success": True}


@router.get("/calibers")
def calibers(request: Request, current_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    records = db.execute(select(
        Caliber.id, Caliber.name, Caliber.is_selectable,
    ).order_by(Caliber.name, Caliber.id)).mappings().all()
    return render(request, current_user, "admin/calibers.html", records=records)


def get_caliber(db: Session, caliber_id: UUID) -> Caliber:
    caliber = db.get(Caliber, caliber_id)
    if caliber is None:
        raise HTTPException(status_code=404, detail="Caliber not found.")
    return caliber


@router.get("/calibers/{caliber_id}/aliases")
def caliber_aliases(
    caliber_id: UUID, request: Request,
    current_user: User = Depends(require_admin), db: Session = Depends(get_db),
):
    caliber = get_caliber(db, caliber_id)
    aliases = db.scalars(
        select(CaliberAlias).where(
            CaliberAlias.caliber_id == caliber.id,
        ).order_by(CaliberAlias.alias, CaliberAlias.id)
    ).all()
    changes = db.execute(
        select(CaliberAliasAuditEvent, User.display_name, User.email)
        .join(User, User.id == CaliberAliasAuditEvent.actor_user_id)
        .where(CaliberAliasAuditEvent.caliber_id == caliber.id)
        .order_by(CaliberAliasAuditEvent.created_at.desc(), CaliberAliasAuditEvent.id)
        .limit(50)
    ).all()
    return render(
        request, current_user, "admin/caliber_aliases.html",
        caliber=caliber, aliases=aliases, changes=changes,
    )


@router.post(
    "/calibers/{caliber_id}/aliases",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def caliber_alias_create(
    caliber_id: UUID, payload: CaliberAliasRequest,
    current_user: User = Depends(require_admin), db: Session = Depends(get_db),
):
    get_caliber(db, caliber_id)
    try:
        alias = add_caliber_alias(
            db, caliber_id, payload.alias, actor_user_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Alias conflicts with an existing caliber name or alias.",
        ) from exc
    return {"success": True, "id": str(alias.id), "alias": alias.alias}


@router.delete(
    "/calibers/{caliber_id}/aliases/{alias_id}",
    dependencies=[Depends(require_csrf)],
)
def caliber_alias_delete(
    caliber_id: UUID, alias_id: UUID, current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    get_caliber(db, caliber_id)
    try:
        delete_caliber_alias(
            db, caliber_id=caliber_id, alias_id=alias_id,
            actor_user_id=current_user.id,
        )
    except ValueError as exc:
        status_code = 404 if str(exc) == "Caliber alias not found." else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return {"success": True}


@router.get("/announcements")
def announcements(request: Request, current_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    records = db.scalars(select(Announcement).order_by(Announcement.starts_at.desc(), Announcement.id)).all()
    return render(request, current_user, "admin/announcements/list.html", announcements=records)


@router.get("/announcements/new")
def announcement_new(request: Request, current_user: User = Depends(require_admin)):
    return render(request, current_user, "admin/announcements/form.html", announcement=None)


def get_announcement(db, announcement_id):
    announcement = db.get(Announcement, announcement_id)
    if announcement is None:
        raise HTTPException(status_code=404, detail="Announcement not found.")
    return announcement


@router.post("/announcements/schedule-preview", dependencies=[Depends(require_csrf)])
def announcement_schedule_preview(payload: SchedulePreview):
    """Use the same server conversion as saves; never write an announcement."""
    try:
        return payload.preview()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/announcements/{announcement_id}/edit")
def announcement_edit(announcement_id: UUID, request: Request, current_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return render(request, current_user, "admin/announcements/form.html", announcement=get_announcement(db, announcement_id))


@router.post("/announcements", status_code=201, dependencies=[Depends(require_csrf)])
def announcement_create(payload: AnnouncementRequest, current_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    announcement = save_announcement(db, payload, current_user.id)
    return {"success": True, "id": str(announcement.id)}


@router.put("/announcements/{announcement_id}", dependencies=[Depends(require_csrf)])
def announcement_update(announcement_id: UUID, payload: AnnouncementRequest, current_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    announcement = save_announcement(db, payload, current_user.id, get_announcement(db, announcement_id))
    return {"success": True, "id": str(announcement.id)}
