from fastapi import Depends, FastAPI, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.db.session import engine

from starlette.middleware.sessions import SessionMiddleware

from app.api.auth import router as auth_router

from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core.dependencies import get_current_user

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
)

app.include_router(auth_router)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    session_cookie="armory_ledger_session",
    https_only=True,
    same_site="lax",
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

templates = Jinja2Templates(directory="app/templates")


@app.get("/")
async def login_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "app_name": settings.app_name,
            "app_version": settings.app_version,
        },
    )

@app.get("/dashboard")
async def dashboard(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "app_name": settings.app_name,
            "app_version": settings.app_version,
            "current_user": current_user,
        },
    )

@app.get("/health")
async def health():
    database_status = "connected"
    overall_status = "healthy"

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        database_status = "unavailable"
        overall_status = "degraded"

    return {
        "status": overall_status,
        "application": settings.app_name,
        "database": database_status,
        "version": settings.app_version,
    }
