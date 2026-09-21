from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User


def sync_oidc_user(
    db: Session,
    *,
    oidc_subject: str,
    email: str,
    display_name: str,
) -> User:
    user = db.scalar(
        select(User).where(User.oidc_subject == oidc_subject)
    )

    now = datetime.now(timezone.utc)

    if user is None:
        user = User(
            oidc_subject=oidc_subject,
            email=email,
            display_name=display_name,
            last_login_at=now,
        )
        db.add(user)
    else:
        user.email = email
        user.display_name = display_name
        user.last_login_at = now

    db.commit()
    db.refresh(user)

    return user
