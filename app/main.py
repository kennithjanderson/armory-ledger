from uuid import UUID

from fastapi import Depends, FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import RedirectResponse

from app.api.accessories import router as accessories_router
from app.api.ammunition import router as ammunition_router
from app.api.auth import router as auth_router
from app.api.firearms import router as firearms_router
from app.api.range import router as range_router
from app.api.reference import router as reference_router

from app.core.config import settings
from app.core.dependencies import get_current_user, get_db
from app.db.session import engine
from app.main_templates import templates

from app.models.accessory import Accessory
from app.models.ammo_lot import AmmoLot
from app.models.firearm import Firearm
from app.models.range_session import RangeSession
from app.models.user import User

from app.services.ammo_inventory_service import get_physical_inventory


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
)


app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    session_cookie="armory_ledger_session",
    https_only=True,
    same_site="lax",
)


PUBLIC_PATHS = {
    "/",
    "/auth/login",
    "/auth/callback",
    "/auth/popup-complete",
    "/health",
}


@app.exception_handler(HTTPException)
async def http_exception_handler(
    request: Request,
    exc: HTTPException,
):
    if exc.status_code == 401:
        return RedirectResponse(
            url="/",
            status_code=303,
        )

    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=exc.headers,
    )


app.mount(
    "/static",
    StaticFiles(directory="app/static"),
    name="static",
)

app.include_router(auth_router)
app.include_router(firearms_router)
app.include_router(ammunition_router)
app.include_router(range_router)
app.include_router(accessories_router)
app.include_router(reference_router)


@app.get("/")
async def login_page(request: Request):
    if "user" in request.session:
        return RedirectResponse(
            url="/dashboard",
            status_code=303,
        )

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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    firearm_count = db.scalar(
        select(func.count())
        .select_from(Firearm)
        .where(Firearm.owner_id == current_user.id)
    ) or 0

    accessory_count = db.scalar(
        select(func.coalesce(func.sum(Accessory.quantity), 0))
        .where(Accessory.owner_id == current_user.id)
    ) or 0

    range_session_count = db.scalar(
        select(func.count())
        .select_from(RangeSession)
        .where(RangeSession.owner_id == current_user.id)
    ) or 0

    ammo_lot_ids = db.scalars(
        select(AmmoLot.id)
        .where(AmmoLot.owner_id == current_user.id)
    ).all()

    rounds_on_hand = sum(
        get_physical_inventory(
            db,
            lot_id=lot_id,
        )
        for lot_id in ammo_lot_ids
    )

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "app_name": settings.app_name,
            "app_version": settings.app_version,
            "current_user": current_user,
            "is_admin": request.session["user"].get(
                "is_admin",
                False,
            ),
            "firearm_count": firearm_count,
            "rounds_on_hand": rounds_on_hand,
            "accessory_count": accessory_count,
            "range_session_count": range_session_count,
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