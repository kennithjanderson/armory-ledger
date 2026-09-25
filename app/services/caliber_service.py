from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.caliber import Caliber
from app.models.caliber_alias import CaliberAlias


def normalize_caliber_name(value: str) -> str:
    return " ".join(value.strip().split())


def get_caliber_by_name_or_alias(
    db: Session,
    name: str,
) -> Caliber | None:
    normalized_name = normalize_caliber_name(name)

    if not normalized_name:
        return None

    canonical_match = db.scalar(
        select(Caliber)
        .where(
            func.lower(Caliber.name)
            == normalized_name.lower()
        )
    )

    if canonical_match is not None:
        return canonical_match

    alias_match = db.scalar(
        select(Caliber)
        .join(
            CaliberAlias,
            CaliberAlias.caliber_id == Caliber.id,
        )
        .where(
            func.lower(CaliberAlias.alias)
            == normalized_name.lower()
        )
    )

    return alias_match


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