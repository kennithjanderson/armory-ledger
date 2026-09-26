from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse
from starlette.responses import RedirectResponse

from app.core.auth import oauth
from app.core.config import settings
from app.core.dependencies import get_current_user

from app.db.session import SessionLocal
from app.models.user import User
from app.services.user_service import sync_oidc_user


router = APIRouter(prefix="/auth", tags=["authentication"])


@router.get("/login")
async def login(
    request: Request,
    popup: bool = False,
):
    request.session["auth_popup"] = popup

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
    if not isinstance(groups, list) or not all(isinstance(group, str) for group in groups):
        groups = []

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

    # A new authenticated session must not reuse a previous CSRF token.
    request.session.pop("csrf_token", None)
    request.session["user"] = {
        "id": user_id,
        "email": email,
        "name": display_name,
        "is_admin": "Armory Admin" in groups,
    }

    popup = request.session.pop("auth_popup", False)

    if popup:
        return RedirectResponse(url="/auth/popup-complete")

    return RedirectResponse(url="/dashboard")

@router.get("/me")
async def me(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    return {
        "authenticated": True,
    }


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/")

@router.get("/popup-complete", response_class=HTMLResponse)
async def popup_complete(request: Request):
    if "user" not in request.session:
        raise HTTPException(
            status_code=401,
            detail="Authentication required.",
        )

    return HTMLResponse(
        content="""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Authentication Complete</title>
</head>
<body>
<script>
    if (window.opener) {
        window.opener.postMessage(
            { type: "armory-authenticated" },
            window.location.origin
        );
    }

    window.close();
</script>
</body>
</html>
"""
    )
