"""Authenticated owner-controlled sharing invitation routes."""
from typing import Literal
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.csrf import csrf_token, require_csrf
from app.core.dependencies import get_current_user, get_db
from app.models.inventory_share import InventoryShare
from app.services import sharing_service
from app.main_templates import templates


router = APIRouter(dependencies=[Depends(get_current_user)])
Access = Literal["none", "ro", "rw"]


class PermissionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    firearms: Access
    ammunition: Access
    accessories: Access
    shooting_log: Access


class InviteBody(PermissionBody):
    email: str = Field(min_length=3, max_length=320)


@router.get("/sharing")
def sharing_page(request: Request, user=Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        sharing_service.claim_pending_invitations(db, user)
    except ValueError:
        # Accounts without a usable email can still review shares already bound
        # to their UUID; they simply cannot claim an unbound invitation.
        pass
    outgoing = db.scalars(
        select(InventoryShare).options(selectinload(InventoryShare.recipient)).where(
            InventoryShare.owner_id == user.id
        ).order_by(InventoryShare.updated_at.desc(), InventoryShare.id)
    ).all()
    incoming = db.scalars(
        select(InventoryShare).options(selectinload(InventoryShare.owner)).where(
            InventoryShare.recipient_id == user.id,
            InventoryShare.status.in_(("pending", "accepted")),
        ).order_by(InventoryShare.updated_at.desc(), InventoryShare.id)
    ).all()
    return templates.TemplateResponse(request=request, name="sharing.html", context={
        "app_name": settings.app_name,
        "app_version": settings.app_version,
        "current_user": user,
        "is_admin": user.is_admin,
        "csrf_token": csrf_token(request),
        "outgoing_shares": outgoing,
        "incoming_shares": incoming,
    })


@router.post("/api/shares", status_code=202, dependencies=[Depends(require_csrf)])
def create_invitation(payload: InviteBody, user=Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        sharing_service.invite(
            db, owner=user, email=payload.email,
            permissions=payload.model_dump(exclude={"email"}),
        )
    except sharing_service.InvitationEmailUnavailable as exc:
        raise HTTPException(503, "Sharing invitations require configured system email") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"message": sharing_service.GENERIC_INVITATION_MESSAGE}


@router.put("/api/shares/{share_id}/permissions", dependencies=[Depends(require_csrf)])
def update_permissions(
    share_id: uuid.UUID,
    payload: PermissionBody,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        share = sharing_service.set_permissions(
            db, owner_id=user.id, share_id=share_id, permissions=payload.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, "Sharing invitation not found") from exc
    return {"id": str(share.id), "permissions": sharing_service.permission_summary(share)}


@router.delete("/api/shares/{share_id}", dependencies=[Depends(require_csrf)])
def revoke_invitation(share_id: uuid.UUID, user=Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        share = sharing_service.revoke(db, owner_id=user.id, share_id=share_id)
    except LookupError as exc:
        raise HTTPException(404, "Sharing invitation not found") from exc
    return {"id": str(share.id), "status": share.status}


@router.post("/api/sharing-invitations/{share_id}/accept", dependencies=[Depends(require_csrf)])
def accept_invitation(share_id: uuid.UUID, user=Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        share = sharing_service.respond(db, recipient=user, share_id=share_id, accept=True)
    except LookupError as exc:
        raise HTTPException(404, "Invitation not found") from exc
    return {"id": str(share.id), "status": share.status}


@router.post("/api/sharing-invitations/{share_id}/decline", dependencies=[Depends(require_csrf)])
def decline_invitation(share_id: uuid.UUID, user=Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        share = sharing_service.respond(db, recipient=user, share_id=share_id, accept=False)
    except LookupError as exc:
        raise HTTPException(404, "Invitation not found") from exc
    return {"id": str(share.id), "status": share.status}
