"""Protect the complete /admin* URL namespace, not just navigation links."""
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, RedirectResponse

from app.core.dependencies import get_current_user, require_admin
from app.db.session import SessionLocal


def check_admin(request):
    with SessionLocal() as db:
        user = get_current_user(request, db)
        require_admin(request, user)


class AdminAccessMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path", "").startswith("/admin"):
            request = Request(scope, receive=receive)
            try:
                await run_in_threadpool(check_admin, request)
            except HTTPException as exc:
                if exc.status_code == 401 and request.method in {"GET", "HEAD"}:
                    response = RedirectResponse("/", status_code=303)
                else:
                    response = JSONResponse(
                        {"detail": exc.detail}, status_code=exc.status_code,
                    )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
