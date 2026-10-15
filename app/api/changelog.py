from fastapi import APIRouter, Request

from app.core.config import settings
from app.main_templates import templates
from app.services.changelog_service import load_changelog

router = APIRouter()


@router.get("/changelog")
def changelog(request: Request):
    """Public software release notes; no inventory queries or authentication dependency."""
    session_user = request.session.get("user")
    # OIDC sessions store "name"; the shared navigation expects display_name.
    current_user = (
        {"display_name": session_user.get("name", "")}
        if session_user else None
    )
    return templates.TemplateResponse(
        request=request, name="changelog.html",
        context={"app_name": settings.app_name, "app_version": settings.app_version,
                 "current_user": current_user,
                 "is_admin": bool(session_user and session_user.get("is_admin") is True),
                 "releases": load_changelog()},
    )
