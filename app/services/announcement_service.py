from sqlalchemy import func, select

from app.models.announcement import Announcement


def active_announcements(db):
    """Request-time evaluation; the end of a window is exclusive."""
    return db.scalars(
        select(Announcement).where(
            Announcement.enabled.is_(True),
            Announcement.starts_at <= func.now(),
            Announcement.ends_at > func.now(),
        ).order_by(Announcement.starts_at, Announcement.id)
    ).all()


def save_announcement(db, payload, actor_id, announcement=None):
    if announcement is None:
        announcement = Announcement(created_by_user_id=actor_id)
        db.add(announcement)
    for name, value in payload.model_dump().items():
        setattr(announcement, name, value)
    announcement.updated_by_user_id = actor_id
    try:
        db.commit()
        db.refresh(announcement)
    except Exception:
        db.rollback()
        raise
    return announcement
