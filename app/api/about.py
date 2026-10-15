from urllib.parse import quote

from fastapi import APIRouter, Request

from app.core.config import settings
from app.main_templates import templates


router = APIRouter()


@router.get("/about")
def about(request: Request):
    session_user = request.session.get("user")
    current_user = {"display_name": session_user.get("name", "")} if session_user else None
    return templates.TemplateResponse(
        request=request, name="about.html",
        context={
            "app_name": settings.app_name, "app_version": settings.app_version,
            "current_user": current_user,
            "is_admin": bool(session_user and session_user.get("is_admin") is True),
            "operator_name": settings.armory_operator_name,
            "support_email": settings.armory_support_email,
            "support_email_href": (
                "mailto:" + quote(settings.armory_support_email, safe="@.")
                if settings.armory_support_email else None
            ),
            "support_url": settings.armory_support_url,
        },
    )
