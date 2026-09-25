from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.accessory import Accessory
from app.models.audit_event import AuditEvent
from app.models.firearm import Firearm
from app.models.organization import Organization


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None

    value = value.strip()
    return value or None


def _validate_location(
    *,
    firearm_id: UUID | None,
    storage_location: str | None,
) -> None:
    if firearm_id is not None and storage_location is not None:
        raise ValueError(
            "An accessory cannot be assigned to a firearm "
            "and a storage location at the same time."
        )


def _get_owned_firearm(
    db: Session,
    *,
    owner_id: UUID,
    firearm_id: UUID,
) -> Firearm:
    firearm = db.scalar(
        select(Firearm).where(
            Firearm.id == firearm_id,
            Firearm.owner_id == owner_id,
        )
    )

    if firearm is None:
        raise LookupError("Firearm not found.")

    return firearm


def get_accessory(
    db: Session,
    *,
    owner_id: UUID,
    accessory_id: UUID,
) -> Accessory:
    accessory = db.scalar(
        select(Accessory)
        .options(
            joinedload(Accessory.manufacturer),
            joinedload(Accessory.firearm),
        )
        .where(
            Accessory.id == accessory_id,
            Accessory.owner_id == owner_id,
        )
    )

    if accessory is None:
        raise LookupError("Accessory not found.")

    return accessory


def create_accessory(
    db: Session,
    *,
    owner_id: UUID,
    name: str,
    quantity: int = 1,
    manufacturer_id: UUID | None = None,
    model: str | None = None,
    serial_number: str | None = None,
    purchase_date: date | None = None,
    purchase_location: str | None = None,
    firearm_id: UUID | None = None,
    storage_location: str | None = None,
    notes: str | None = None,
) -> Accessory:
    name = name.strip()

    if not name:
        raise ValueError("Accessory name is required.")

    if quantity < 1:
        raise ValueError("Accessory quantity must be at least 1.")

    model = _clean_optional(model)
    serial_number = _clean_optional(serial_number)
    purchase_location = _clean_optional(purchase_location)
    storage_location = _clean_optional(storage_location)
    notes = _clean_optional(notes)

    _validate_location(
        firearm_id=firearm_id,
        storage_location=storage_location,
    )

    if manufacturer_id is not None:
        manufacturer = db.get(Organization, manufacturer_id)

        if manufacturer is None:
            raise LookupError("Manufacturer not found.")

    if firearm_id is not None:
        _get_owned_firearm(
            db,
            owner_id=owner_id,
            firearm_id=firearm_id,
        )

    accessory = Accessory(
        owner_id=owner_id,
        name=name,
        quantity=quantity,
        manufacturer_id=manufacturer_id,
        model=model,
        serial_number=serial_number,
        purchase_date=purchase_date,
        purchase_location=purchase_location,
        firearm_id=firearm_id,
        storage_location=storage_location,
        notes=notes,
    )

    db.add(accessory)

    try:
        db.commit()
        db.refresh(accessory)
    except Exception:
        db.rollback()
        raise

    return accessory

def update_accessory(
    db: Session,
    *,
    owner_id: UUID,
    actor_user_id: UUID,
    accessory_id: UUID,
    name: str,
    quantity: int = 1,
    manufacturer_id: UUID | None = None,
    model: str | None = None,
    serial_number: str | None = None,
    purchase_date: date | None = None,
    purchase_location: str | None = None,
    firearm_id: UUID | None = None,
    storage_location: str | None = None,
    notes: str | None = None,
) -> Accessory:
    accessory = get_accessory(
        db,
        owner_id=owner_id,
        accessory_id=accessory_id,
    )

    name = name.strip()

    if not name:
        raise ValueError("Accessory name is required.")

    if quantity < 1:
        raise ValueError("Accessory quantity must be at least 1.")

    model = _clean_optional(model)
    serial_number = _clean_optional(serial_number)
    purchase_location = _clean_optional(purchase_location)
    storage_location = _clean_optional(storage_location)
    notes = _clean_optional(notes)

    _validate_location(
        firearm_id=firearm_id,
        storage_location=storage_location,
    )

    if manufacturer_id is not None:
        manufacturer = db.get(Organization, manufacturer_id)

        if manufacturer is None:
            raise LookupError("Manufacturer not found.")

    if firearm_id is not None:
        _get_owned_firearm(
            db,
            owner_id=owner_id,
            firearm_id=firearm_id,
        )

    changes = {}

    fields = {
        "name": name,
        "quantity": quantity,
        "manufacturer_id": manufacturer_id,
        "model": model,
        "serial_number": serial_number,
        "purchase_date": purchase_date,
        "purchase_location": purchase_location,
        "firearm_id": firearm_id,
        "storage_location": storage_location,
        "notes": notes,
    }

    for field_name, new_value in fields.items():
        old_value = getattr(accessory, field_name)

        if old_value != new_value:
            changes[field_name] = {
                "old": (
                    str(old_value)
                    if old_value is not None
                    else None
                ),
                "new": (
                    str(new_value)
                    if new_value is not None
                    else None
                ),
            }

            setattr(accessory, field_name, new_value)

    if not changes:
        return accessory

    audit_event = AuditEvent(
        owner_id=owner_id,
        actor_user_id=actor_user_id,
        entity_type="accessory",
        entity_id=accessory.id,
        action="updated",
        changes=changes,
    )

    db.add(audit_event)

    try:
        db.commit()
        db.refresh(accessory)
    except Exception:
        db.rollback()
        raise

    return accessory