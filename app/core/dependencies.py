from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.user import User


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    session_user = request.session.get("user")

    if not session_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    user_id = session_user.get("id")

    if not user_id:
        request.session.clear()

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication session.",
        )

    try:
        user_uuid = UUID(user_id)
    except (TypeError, ValueError):
        request.session.clear()

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication session.",
        )

    user = db.get(User, user_uuid)

    if user is None:
        request.session.clear()

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account no longer exists.",
        )

    return user


def require_admin(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> User:
    # Login already requires Armory User. Armory Admin is additional authority.
    if request.session.get("user", {}).get("is_admin") is not True:
        raise HTTPException(status_code=403, detail="Armory Admin access required.")
    return current_user
