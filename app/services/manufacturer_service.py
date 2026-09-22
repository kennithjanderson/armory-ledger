from difflib import SequenceMatcher
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.organization import Organization, ManufacturerProfile
from app.models.organization_alias import OrganizationAlias


def normalize_name(value: str) -> str:
    """
    Conservative normalization used for comparisons.

    We intentionally do not replace punctuation, "&", "and",
    corporate suffixes, etc. Those belong in aliases.
    """
    return " ".join(value.strip().lower().split())


def find_exact_manufacturer(
    db: Session,
    search_term: str,
) -> Organization | None:
    """
    Find a selectable manufacturer by either its canonical
    organization name or one of its aliases.
    """
    normalized = normalize_name(search_term)

    if not normalized:
        return None

    # Canonical organization name
    organization = db.scalar(
        select(Organization)
        .join(
            ManufacturerProfile,
            ManufacturerProfile.organization_id == Organization.id,
        )
        .where(
            ManufacturerProfile.is_selectable.is_(True),
            func.lower(func.trim(Organization.name)) == normalized,
        )
    )

    if organization is not None:
        return organization

    # Organization alias
    organization = db.scalar(
        select(Organization)
        .join(
            ManufacturerProfile,
            ManufacturerProfile.organization_id == Organization.id,
        )
        .join(
            OrganizationAlias,
            OrganizationAlias.organization_id == Organization.id,
        )
        .where(
            ManufacturerProfile.is_selectable.is_(True),
            func.lower(func.trim(OrganizationAlias.alias)) == normalized,
        )
    )

    return organization


def find_similar_manufacturers(
    db: Session,
    search_term: str,
    *,
    threshold: float = 0.60,
    limit: int = 5,
) -> list[tuple[Organization, float]]:
    """
    Return possible manufacturer matches.

    Similarity results are suggestions only. They must never
    automatically select or merge organizations.
    """
    normalized_search = normalize_name(search_term)

    if not normalized_search:
        return []

    organizations = db.scalars(
        select(Organization)
        .join(
            ManufacturerProfile,
            ManufacturerProfile.organization_id == Organization.id,
        )
        .where(ManufacturerProfile.is_selectable.is_(True))
        .order_by(Organization.name)
    ).all()

    results: list[tuple[Organization, float]] = []

    for organization in organizations:
        candidate_names = [organization.name]

        aliases = db.scalars(
            select(OrganizationAlias.alias).where(
                OrganizationAlias.organization_id == organization.id
            )
        ).all()

        candidate_names.extend(aliases)

        best_score = 0.0

        for candidate in candidate_names:
            score = SequenceMatcher(
                None,
                normalized_search,
                normalize_name(candidate),
            ).ratio()

            best_score = max(best_score, score)

        if best_score >= threshold:
            results.append((organization, best_score))

    results.sort(key=lambda item: item[1], reverse=True)

    return results[:limit]


def create_manufacturer(
    db: Session,
    name: str,
    *,
    commit: bool = True,
) -> Organization:
    """
    Create a new selectable manufacturer.

    Refuses creation when the supplied name already resolves to an
    existing canonical manufacturer name or alias.
    """
    cleaned_name = " ".join(name.strip().split())

    if not cleaned_name:
        raise ValueError("Manufacturer name cannot be empty.")

    existing = find_exact_manufacturer(db, cleaned_name)

    if existing is not None:
        raise ValueError(
            f'Manufacturer already exists as "{existing.name}".'
        )

    organization = Organization(
        name=cleaned_name,
    )

    db.add(organization)
    db.flush()

    profile = ManufacturerProfile(
        organization_id=organization.id,
        is_selectable=True,
    )

    db.add(profile)

    if commit:
        db.commit()
        db.refresh(organization)
    else:
        db.flush()

    return organization


def add_manufacturer_alias(
    db: Session,
    organization_id: UUID,
    alias: str,
) -> OrganizationAlias:
    """
    Add an alias to an existing manufacturer.

    Refuses aliases that already resolve to another canonical
    manufacturer or alias.
    """
    cleaned_alias = " ".join(alias.strip().split())

    if not cleaned_alias:
        raise ValueError("Alias cannot be empty.")

    organization = db.get(Organization, organization_id)

    if organization is None:
        raise ValueError("Manufacturer does not exist.")

    existing = find_exact_manufacturer(db, cleaned_alias)

    if existing is not None:
        if existing.id == organization.id:
            raise ValueError(
                f'"{cleaned_alias}" already resolves to "{organization.name}".'
            )

        raise ValueError(
            f'"{cleaned_alias}" already resolves to another manufacturer: '
            f'"{existing.name}".'
        )

    new_alias = OrganizationAlias(
        organization_id=organization.id,
        alias=cleaned_alias,
    )

    db.add(new_alias)
    db.commit()
    db.refresh(new_alias)

    return new_alias
