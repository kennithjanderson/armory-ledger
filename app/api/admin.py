from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.csrf import csrf_token, require_csrf
from app.core.dependencies import get_db, require_admin
from app.main_templates import templates
from app.models.announcement import Announcement
from app.models.caliber import Caliber
from app.models.organization import ManufacturerProfile, Organization
from app.models.user import User
from app.schemas.announcement import AnnouncementRequest
from app.services.announcement_service import save_announcement


router = APIRouter(prefix="/admin", tags=["administration"], dependencies=[Depends(require_admin)])


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


@router.get("/calibers")
def calibers(request: Request, current_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    records = db.execute(select(
        Caliber.id, Caliber.name, Caliber.is_selectable,
    ).order_by(Caliber.name, Caliber.id)).mappings().all()
    return render(request, current_user, "admin/calibers.html", records=records)


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
