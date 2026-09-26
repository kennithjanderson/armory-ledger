import secrets

from fastapi import HTTPException, Request


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def require_csrf(request: Request) -> None:
    expected = request.session.get("csrf_token")
    supplied = request.headers.get("X-CSRF-Token", "")
    if not expected or not supplied.isascii() or not secrets.compare_digest(expected, supplied):
        raise HTTPException(status_code=403, detail="Invalid request token. Reload the page.")
