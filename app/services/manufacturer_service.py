from difflib import SequenceMatcher
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, selectinload

from app.models.organization import Organization, ManufacturerProfile
from app.models.organization_alias import OrganizationAlias
from app.models.manufacturer_alias_audit_event import ManufacturerAliasAuditEvent
from app.models.reference_name_audit_event import ReferenceNameAuditEvent


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
    alias_query = (
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

    organization = db.scalar(alias_query)

    return organization


def _lock_manufacturer_catalog(db: Session) -> None:
    """Serialize canonical-name and alias conflict checks on PostgreSQL."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(4286797, 5062215)"))


def _clean_alias(alias: str) -> str:
    cleaned = " ".join(alias.strip().split())
    if not cleaned:
        raise ValueError("Alias cannot be empty.")
    return cleaned


def _record_alias_change(
    db: Session,
    *,
    organization_id: UUID,
    alias_id: UUID,
    actor_user_id: UUID,
    action: str,
    previous_alias: str | None,
    new_alias: str | None,
) -> None:
    db.add(ManufacturerAliasAuditEvent(
        manufacturer_id=organization_id,
        alias_id=alias_id,
        actor_user_id=actor_user_id,
        action=action,
        previous_alias=previous_alias,
        new_alias=new_alias,
    ))


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

    _lock_manufacturer_catalog(db)
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
    *,
    actor_user_id: UUID,
) -> OrganizationAlias:
    """
    Add an alias to an existing manufacturer.

    Refuses aliases that already resolve to another canonical
    manufacturer or alias.
    """
    cleaned_alias = _clean_alias(alias)

    organization = db.get(Organization, organization_id)

    if organization is None:
        raise ValueError("Manufacturer does not exist.")

    _lock_manufacturer_catalog(db)
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
    db.flush()
    _record_alias_change(
        db, organization_id=organization.id, alias_id=new_alias.id,
        actor_user_id=actor_user_id, action="created", previous_alias=None,
        new_alias=new_alias.alias,
    )
    db.commit()
    db.refresh(new_alias)

    return new_alias


def delete_manufacturer_alias(
    db: Session,
    *,
    organization_id: UUID,
    alias_id: UUID,
    actor_user_id: UUID,
) -> None:
    _lock_manufacturer_catalog(db)
    record = db.scalar(
        select(OrganizationAlias).where(
            OrganizationAlias.id == alias_id,
            OrganizationAlias.organization_id == organization_id,
        ).with_for_update()
    )
    if record is None:
        raise ValueError("Manufacturer alias not found.")

    previous_alias = record.alias
    db.delete(record)
    _record_alias_change(
        db, organization_id=organization_id, alias_id=alias_id,
        actor_user_id=actor_user_id, action="deleted",
        previous_alias=previous_alias, new_alias=None,
    )
    db.commit()


def rename_manufacturer(
    db: Session,
    manufacturer_id: UUID,
    name: str,
    *,
    actor_user_id: UUID,
) -> Organization:
    """Rename one shared manufacturer, preserving the former name as an alias."""
    cleaned_name = " ".join(name.strip().split())
    if not cleaned_name:
        raise ValueError("Manufacturer name cannot be empty.")
    if len(cleaned_name) > 255:
        raise ValueError("Manufacturer name cannot exceed 255 characters.")

    _lock_manufacturer_catalog(db)
    organization = db.scalar(
        select(Organization)
        .join(ManufacturerProfile, ManufacturerProfile.organization_id == Organization.id)
        .where(Organization.id == manufacturer_id)
        .options(selectinload(Organization.aliases))
        .with_for_update()
    )
    if organization is None:
        raise ValueError("Manufacturer does not exist.")

    previous_name = organization.name
    if normalize_name(previous_name) == normalize_name(cleaned_name):
        return organization

    # Check every organization, including non-selectable or non-manufacturer
    # organizations, because Organization.name is globally unique and aliases
    # share the same normalized namespace.
    organizations = db.scalars(
        select(Organization).options(selectinload(Organization.aliases))
    ).unique().all()
    target = normalize_name(cleaned_name)
    matches: list[tuple[Organization, OrganizationAlias | None]] = []
    for candidate in organizations:
        if normalize_name(candidate.name) == target:
            matches.append((candidate, None))
        matches.extend(
            (candidate, alias) for alias in candidate.aliases
            if normalize_name(alias.alias) == target
        )

    if any(candidate.id != organization.id for candidate, _ in matches):
        raise ValueError("Manufacturer name conflicts with another canonical name or alias.")
    promoted_alias = next((alias for candidate, alias in matches if candidate.id == organization.id), None)
    if len(matches) > 1:
        raise ValueError("Manufacturer name ambiguously matches existing reference data.")

    former_label = " ".join(previous_name.strip().split())
    old_label_matches = [
        (candidate, alias)
        for candidate in organizations
        for alias in candidate.aliases
        if normalize_name(alias.alias) == normalize_name(former_label)
    ]
    if any(candidate.id != organization.id for candidate, _ in old_label_matches):
        raise ValueError("The current manufacturer name conflicts with another reference alias.")

    if promoted_alias is not None:
        db.delete(promoted_alias)
        _record_alias_change(
            db, organization_id=organization.id, alias_id=promoted_alias.id,
            actor_user_id=actor_user_id, action="deleted",
            previous_alias=promoted_alias.alias, new_alias=None,
        )

    existing_former_alias = next((alias for _, alias in old_label_matches), None)
    if existing_former_alias is None:
        former_alias = OrganizationAlias(organization_id=organization.id, alias=former_label)
        db.add(former_alias)
        db.flush()
        _record_alias_change(
            db, organization_id=organization.id, alias_id=former_alias.id,
            actor_user_id=actor_user_id, action="created", previous_alias=None,
            new_alias=former_alias.alias,
        )

    organization.name = cleaned_name
    db.add(ReferenceNameAuditEvent(
        reference_type="manufacturer", reference_id=organization.id,
        actor_user_id=actor_user_id, previous_name=previous_name, new_name=cleaned_name,
    ))
    db.commit()
    db.refresh(organization)
    return organization
