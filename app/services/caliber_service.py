from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from app.models.caliber import Caliber
from app.models.caliber_alias import CaliberAlias
from app.models.caliber_alias_audit_event import CaliberAliasAuditEvent


def normalize_caliber_name(value: str) -> str:
    return " ".join(value.strip().split())


def _lock_caliber_catalog(db: Session) -> None:
    """Serialize canonical-name and alias conflict checks on PostgreSQL."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(4286797, 5062216)"))


def list_selectable_calibers(db: Session) -> list[Caliber]:
    return db.scalars(
        select(Caliber)
        .options(selectinload(Caliber.aliases))
        .where(Caliber.is_selectable.is_(True))
        .order_by(Caliber.name, Caliber.id)
    ).all()


def get_caliber_by_name_or_alias(
    db: Session,
    name: str,
) -> Caliber | None:
    normalized_name = normalize_caliber_name(name)

    if not normalized_name:
        return None

    calibers = db.scalars(
        select(Caliber).options(selectinload(Caliber.aliases))
        .order_by(Caliber.name, Caliber.id)
    ).all()
    target = normalized_name.lower()
    matches = [
        caliber for caliber in calibers
        if normalize_caliber_name(caliber.name).lower() == target
        or any(normalize_caliber_name(alias.alias).lower() == target for alias in caliber.aliases)
    ]
    if len(matches) > 1:
        raise ValueError(f'"{normalized_name}" ambiguously matches multiple calibers.')
    return matches[0] if matches else None


def create_caliber(
    db: Session,
    name: str,
) -> Caliber:
    normalized_name = normalize_caliber_name(name)

    if not normalized_name:
        raise ValueError("Caliber name is required.")

    if len(normalized_name) > 100:
        raise ValueError(
            "Caliber name cannot exceed 100 characters."
        )

    _lock_caliber_catalog(db)
    existing = get_caliber_by_name_or_alias(
        db,
        normalized_name,
    )

    if existing is not None:
        raise ValueError(
            f'Caliber "{existing.name}" already exists.'
        )

    caliber = Caliber(
        name=normalized_name,
        is_selectable=True,
    )

    db.add(caliber)
    db.commit()
    db.refresh(caliber)

    return caliber


def add_caliber_alias(
    db: Session,
    caliber_id: UUID,
    alias: str,
    *,
    actor_user_id: UUID,
) -> CaliberAlias:
    cleaned_alias = normalize_caliber_name(alias)
    if not cleaned_alias:
        raise ValueError("Alias cannot be empty.")
    if len(cleaned_alias) > 100:
        raise ValueError("Alias cannot exceed 100 characters.")

    caliber = db.get(Caliber, caliber_id)
    if caliber is None:
        raise ValueError("Caliber does not exist.")

    _lock_caliber_catalog(db)
    existing = get_caliber_by_name_or_alias(db, cleaned_alias)
    if existing is not None:
        if existing.id == caliber.id:
            raise ValueError(f'"{cleaned_alias}" already resolves to "{caliber.name}".')
        raise ValueError(
            f'"{cleaned_alias}" already resolves to another caliber: "{existing.name}".'
        )

    record = CaliberAlias(caliber_id=caliber.id, alias=cleaned_alias)
    db.add(record)
    db.flush()
    db.add(CaliberAliasAuditEvent(
        caliber_id=caliber.id, alias_id=record.id, actor_user_id=actor_user_id,
        action="created", previous_alias=None, new_alias=record.alias,
    ))
    db.commit()
    db.refresh(record)
    return record


def delete_caliber_alias(
    db: Session,
    *,
    caliber_id: UUID,
    alias_id: UUID,
    actor_user_id: UUID,
) -> None:
    _lock_caliber_catalog(db)
    record = db.scalar(
        select(CaliberAlias).where(
            CaliberAlias.id == alias_id,
            CaliberAlias.caliber_id == caliber_id,
        ).with_for_update()
    )
    if record is None:
        raise ValueError("Caliber alias not found.")

    previous_alias = record.alias
    db.delete(record)
    db.add(CaliberAliasAuditEvent(
        caliber_id=caliber_id, alias_id=alias_id, actor_user_id=actor_user_id,
        action="deleted", previous_alias=previous_alias, new_alias=None,
    ))
    db.commit()
