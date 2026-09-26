from urllib.parse import quote

from fastapi import APIRouter, Depends, Request

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.main_templates import templates
from app.models.user import User


router = APIRouter()


@router.get("/about")
def about(request: Request, current_user: User = Depends(get_current_user)):
    return templates.TemplateResponse(
        request=request, name="about.html",
        context={
            "app_name": settings.app_name, "app_version": settings.app_version,
            "current_user": current_user,
            "is_admin": request.session["user"].get("is_admin") is True,
            "operator_name": settings.armory_operator_name,
            "support_email": settings.armory_support_email,
            "support_email_href": (
                "mailto:" + quote(settings.armory_support_email, safe="@.")
                if settings.armory_support_email else None
            ),
            "support_url": settings.armory_support_url,
        },
    )
