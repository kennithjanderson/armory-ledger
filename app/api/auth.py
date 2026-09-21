from fastapi import APIRouter, Request, APIRouter, HTTPException, Request
from starlette.responses import RedirectResponse

from app.core.auth import oauth
from app.core.config import settings

from app.db.session import SessionLocal
from app.services.user_service import sync_oidc_user


router = APIRouter(prefix="/auth", tags=["authentication"])


@router.get("/login")
async def login(request: Request):
    return await oauth.authentik.authorize_redirect(
        request,
        settings.oidc_redirect_uri,
    )


@router.get("/callback")
async def callback(request: Request):
    token = await oauth.authentik.authorize_access_token(request)

    userinfo = token.get("userinfo")

    if not userinfo:
        userinfo = await oauth.authentik.userinfo(token=token)

    oidc_subject = userinfo.get("sub")
    email = userinfo.get("email")
    display_name = userinfo.get("name") or email
    groups = userinfo.get("groups", [])

    if not oidc_subject or not email:
        raise HTTPException(
            status_code=400,
            detail="OIDC provider did not return required identity claims.",
        )

    if "Armory User" not in groups:
        raise HTTPException(
            status_code=403,
            detail="User is not authorized to access Armory Ledger.",
        )

    with SessionLocal() as db:
        user = sync_oidc_user(
            db,
            oidc_subject=oidc_subject,
            email=email,
            display_name=display_name,
        )

        user_id = str(user.id)

    request.session["user"] = {
        "id": user_id,
        "email": email,
        "name": display_name,
        "is_admin": "Armory Admin" in groups,
    }

    return RedirectResponse(url="/auth/me")

@router.get("/me")
async def me(request: Request):
    return {
        "authenticated": "user" in request.session,
        "user": request.session.get("user"),
    }


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/")
