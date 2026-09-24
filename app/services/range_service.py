from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit_event import AuditEvent
from app.models.ammo_inventory_transaction import AmmoTransactionType
from app.models.firearm import Firearm, FirearmStatus
from app.models.range_session import RangeSession
from app.models.range_session_ammo_usage import (
    RangeAmmoSourceType,
    RangeSessionAmmoUsage,
)
from app.models.range_session_firearm import RangeSessionFirearm
from app.services.ammo_inventory_service import (
    record_inventory_activity,
)

from app.models.ammo_lot import AmmoLot


@dataclass
class RangeAmmoUsageInput:
    source_type: RangeAmmoSourceType
    quantity: int
    ammo_lot_id: UUID | None = None
    description: str | None = None
    range_session_ammo_usage_id: UUID | None = None


@dataclass
class RangeFirearmInput:
    firearm_id: UUID
    notes: str | None = None
    ammo_usage: list[RangeAmmoUsageInput] | None = None
    range_session_firearm_id: UUID | None = None


def create_range_session(
    db: Session,
    *,
    owner_id: UUID,
    actor_user_id: UUID,
    occurred_date: date,
    location: str | None,
    notes: str | None,
    firearms: list[RangeFirearmInput],
) -> RangeSession:
    if not firearms:
        raise ValueError(
            "A range session must include at least one firearm."
        )

    location = location.strip() if location else None
    location = location or None

    notes = notes.strip() if notes else None
    notes = notes or None

    firearm_ids = [item.firearm_id for item in firearms]

    if len(firearm_ids) != len(set(firearm_ids)):
        raise ValueError(
            "A firearm cannot be added to the same range session twice."
        )

    try:
        owned_firearms = db.scalars(
            select(Firearm).where(
                Firearm.id.in_(firearm_ids),
                Firearm.owner_id == owner_id,
            )
        ).all()

        if len(owned_firearms) != len(firearm_ids):
            raise LookupError(
                "One or more firearms were not found."
            )

        if any(
            firearm.status != FirearmStatus.OWNED
            for firearm in owned_firearms
        ):
            raise ValueError(
                "Only currently owned firearms can be added "
                "to a new range session."
            )

        range_session = RangeSession(
            owner_id=owner_id,
            occurred_date=occurred_date,
            location=location,
            notes=notes,
        )

        db.add(range_session)
        db.flush()

        for firearm_input in firearms:
            if not firearm_input.ammo_usage:
                raise ValueError(
                    "Each firearm must include at least one ammunition entry."
                )

            firearm_notes = (
                firearm_input.notes.strip()
                if firearm_input.notes
                else None
            )
            firearm_notes = firearm_notes or None

            range_firearm = RangeSessionFirearm(
                range_session_id=range_session.id,
                firearm_id=firearm_input.firearm_id,
                notes=firearm_notes,
            )

            db.add(range_firearm)
            db.flush()

            for ammo_input in firearm_input.ammo_usage or []:
                if ammo_input.quantity <= 0:
                    raise ValueError(
                        "Ammo quantity must be greater than zero."
                    )

                description = (
                    ammo_input.description.strip()
                    if ammo_input.description
                    else None
                )
                description = description or None

                if (
                    ammo_input.source_type
                    == RangeAmmoSourceType.INVENTORY
                ):
                    if ammo_input.ammo_lot_id is None:
                        raise ValueError(
                            "Inventory ammo requires an ammunition lot."
                        )

                    transaction = record_inventory_activity(
                        db,
                        lot_id=ammo_input.ammo_lot_id,
                        owner_id=owner_id,
                        actor_user_id=actor_user_id,
                        transaction_type=AmmoTransactionType.EXPENDED,
                        quantity=ammo_input.quantity,
                        occurred_date=occurred_date,
                        notes="Range session expenditure.",
                        commit=False,
                    )

                    db.add(
                        RangeSessionAmmoUsage(
                            range_session_firearm_id=range_firearm.id,
                            ammo_lot_id=ammo_input.ammo_lot_id,
                            inventory_transaction_id=transaction.id,
                            source_type=RangeAmmoSourceType.INVENTORY,
                            quantity=ammo_input.quantity,
                            description=description,
                        )
                    )

                elif (
                    ammo_input.source_type
                    == RangeAmmoSourceType.OTHER
                ):
                    if ammo_input.ammo_lot_id is not None:
                        raise ValueError(
                            "Other ammo cannot reference an ammunition lot."
                        )

                    db.add(
                        RangeSessionAmmoUsage(
                            range_session_firearm_id=range_firearm.id,
                            ammo_lot_id=None,
                            inventory_transaction_id=None,
                            source_type=RangeAmmoSourceType.OTHER,
                            quantity=ammo_input.quantity,
                            description=description,
                        )
                    )

                else:
                    raise ValueError(
                        "Invalid range ammo source type."
                    )

        db.add(
            AuditEvent(
                owner_id=owner_id,
                actor_user_id=actor_user_id,
                entity_type="range_session",
                entity_id=range_session.id,
                action="created",
                changes={
                    "occurred_date": occurred_date.isoformat(),
                    "location": location,
                    "notes": notes,
                    "firearm_ids": [
                        str(firearm_id)
                        for firearm_id in firearm_ids
                    ],
                },
            )
        )

        db.commit()
        db.refresh(range_session)

        return range_session

    except Exception:
        db.rollback()
        raise

def update_range_session(
    db: Session,
    *,
    range_session_id: UUID,
    owner_id: UUID,
    actor_user_id: UUID,
    occurred_date: date,
    location: str | None,
    notes: str | None,
    firearms: list[RangeFirearmInput],
) -> RangeSession:
    if not firearms:
        raise ValueError(
            "A range session must include at least one firearm."
        )

    location = location.strip() if location else None
    location = location or None

    notes = notes.strip() if notes else None
    notes = notes or None

    firearm_ids = [item.firearm_id for item in firearms]

    if len(firearm_ids) != len(set(firearm_ids)):
        raise ValueError(
            "A firearm cannot be added to the same range session twice."
        )

    try:
        range_session = db.scalar(
            select(RangeSession).where(
                RangeSession.id == range_session_id,
                RangeSession.owner_id == owner_id,
            )
        )

        if range_session is None:
            raise LookupError("Range session not found.")

        owned_firearms = db.scalars(
            select(Firearm).where(
                Firearm.id.in_(firearm_ids),
                Firearm.owner_id == owner_id,
            )
        ).all()

        if len(owned_firearms) != len(firearm_ids):
            raise LookupError(
                "One or more firearms were not found."
            )

        existing_firearms = db.scalars(
            select(RangeSessionFirearm).where(
                RangeSessionFirearm.range_session_id
                == range_session.id
            )
        ).all()

        existing_firearm_ids = {
            item.firearm_id
            for item in existing_firearms
        }

        owned_firearms_by_id = {
            firearm.id: firearm
            for firearm in owned_firearms
        }

        for firearm_input in firearms:
            firearm = owned_firearms_by_id[
                firearm_input.firearm_id
            ]

            if (
                firearm.status != FirearmStatus.OWNED
                and firearm.id not in existing_firearm_ids
            ):
                raise ValueError(
                    "Only currently owned firearms can be added "
                    "to a range session."
                )

        existing_firearms_by_id = {
            item.id: item
            for item in existing_firearms
        }

        existing_usage = db.scalars(
            select(RangeSessionAmmoUsage)
            .join(
                RangeSessionFirearm,
                RangeSessionAmmoUsage.range_session_firearm_id
                == RangeSessionFirearm.id,
            )
            .where(
                RangeSessionFirearm.range_session_id
                == range_session.id
            )
        ).all()

        existing_usage_by_id = {
            item.id: item
            for item in existing_usage
        }

        submitted_firearm_record_ids = {
            item.range_session_firearm_id
            for item in firearms
            if item.range_session_firearm_id is not None
        }

        submitted_usage_ids = {
            ammo.range_session_ammo_usage_id
            for firearm in firearms
            for ammo in (firearm.ammo_usage or [])
            if ammo.range_session_ammo_usage_id is not None
        }

        if not submitted_firearm_record_ids.issubset(
            existing_firearms_by_id.keys()
        ):
            raise LookupError(
                "One or more range firearm records were not found."
            )

        if not submitted_usage_ids.issubset(
            existing_usage_by_id.keys()
        ):
            raise LookupError(
                "One or more range ammunition records were not found."
            )

        old_session_values = {
            "occurred_date": range_session.occurred_date.isoformat(),
            "location": range_session.location,
            "notes": range_session.notes,
        }

        correction_transaction_ids: list[str] = []

        def record_correction(
            *,
            lot_id: UUID,
            transaction_type: AmmoTransactionType,
            quantity: int,
            usage_id: UUID | None,
        ):
            transaction = record_inventory_activity(
                db,
                lot_id=lot_id,
                owner_id=owner_id,
                actor_user_id=actor_user_id,
                transaction_type=transaction_type,
                quantity=quantity,
                occurred_date=occurred_date,
                notes="Range session correction.",
                audit_context={
                    "source": "range_session_correction",
                    "range_session_id": str(range_session.id),
                    "range_ammo_usage_id": (
                        str(usage_id)
                        if usage_id is not None
                        else None
                    ),
                },
                commit=False,
            )

            correction_transaction_ids.append(
                str(transaction.id)
            )

            return transaction

        def restore_inventory_usage(
            usage: RangeSessionAmmoUsage,
        ) -> None:
            if (
                usage.source_type
                == RangeAmmoSourceType.INVENTORY
            ):
                if usage.ammo_lot_id is None:
                    raise ValueError(
                        "Inventory range usage is missing its ammunition lot."
                    )

                record_correction(
                    lot_id=usage.ammo_lot_id,
                    transaction_type=(
                        AmmoTransactionType.ADJUSTMENT_IN
                    ),
                    quantity=usage.quantity,
                    usage_id=usage.id,
                )

        # Reconcile or remove existing ammo usage.
        for usage in existing_usage:
            if usage.id not in submitted_usage_ids:
                restore_inventory_usage(usage)
                db.delete(usage)

        # Remove firearm associations omitted from the request.
        for existing_firearm in existing_firearms:
            if (
                existing_firearm.id
                not in submitted_firearm_record_ids
            ):
                db.delete(existing_firearm)

        # Apply submitted firearm records.
        for firearm_input in firearms:
            if not firearm_input.ammo_usage:
                raise ValueError(
                    "Each firearm must include at least one ammunition entry."
                )

            firearm_notes = (
                firearm_input.notes.strip()
                if firearm_input.notes
                else None
            )
            firearm_notes = firearm_notes or None

            if firearm_input.range_session_firearm_id is None:
                range_firearm = RangeSessionFirearm(
                    range_session_id=range_session.id,
                    firearm_id=firearm_input.firearm_id,
                    notes=firearm_notes,
                )

                db.add(range_firearm)
                db.flush()

            else:
                range_firearm = existing_firearms_by_id[
                    firearm_input.range_session_firearm_id
                ]

                range_firearm.firearm_id = (
                    firearm_input.firearm_id
                )
                range_firearm.notes = firearm_notes

            for ammo_input in firearm_input.ammo_usage or []:
                if ammo_input.quantity <= 0:
                    raise ValueError(
                        "Ammo quantity must be greater than zero."
                    )

                description = (
                    ammo_input.description.strip()
                    if ammo_input.description
                    else None
                )
                description = description or None

                if (
                    ammo_input.source_type
                    == RangeAmmoSourceType.INVENTORY
                ):
                    if ammo_input.ammo_lot_id is None:
                        raise ValueError(
                            "Inventory ammo requires an ammunition lot."
                        )

                    owned_lot = db.scalar(
                        select(AmmoLot).where(
                            AmmoLot.id
                            == ammo_input.ammo_lot_id,
                            AmmoLot.owner_id
                            == owner_id,
                        )
                    )

                    if owned_lot is None:
                        raise LookupError(
                            "Ammunition lot not found."
                        )

                elif (
                    ammo_input.source_type
                    == RangeAmmoSourceType.OTHER
                ):
                    if ammo_input.ammo_lot_id is not None:
                        raise ValueError(
                            "Other ammo cannot reference an ammunition lot."
                        )

                else:
                    raise ValueError(
                        "Invalid range ammo source type."
                    )

                # Brand-new ammo usage.
                if (
                    ammo_input.range_session_ammo_usage_id
                    is None
                ):
                    inventory_transaction = None

                    if (
                        ammo_input.source_type
                        == RangeAmmoSourceType.INVENTORY
                    ):
                        inventory_transaction = (
                            record_inventory_activity(
                                db,
                                lot_id=ammo_input.ammo_lot_id,
                                owner_id=owner_id,
                                actor_user_id=actor_user_id,
                                transaction_type=(
                                    AmmoTransactionType.EXPENDED
                                ),
                                quantity=ammo_input.quantity,
                                occurred_date=occurred_date,
                                notes=(
                                    "Range session expenditure."
                                ),
                                audit_context={
                                    "source": "range_session",
                                    "range_session_id": str(
                                        range_session.id
                                    ),
                                },
                                commit=False,
                            )
                        )

                    new_usage = RangeSessionAmmoUsage(
                        range_session_firearm_id=(
                            range_firearm.id
                        ),
                        ammo_lot_id=(
                            ammo_input.ammo_lot_id
                            if ammo_input.source_type
                            == RangeAmmoSourceType.INVENTORY
                            else None
                        ),
                        inventory_transaction_id=(
                            inventory_transaction.id
                            if inventory_transaction
                            else None
                        ),
                        source_type=ammo_input.source_type,
                        quantity=ammo_input.quantity,
                        description=description,
                    )

                    db.add(new_usage)
                    db.flush()

                    continue

                usage = existing_usage_by_id[
                    ammo_input.range_session_ammo_usage_id
                ]

                # An existing usage cannot be moved under some
                # other range firearm record by manipulating IDs.
                if (
                    usage.range_session_firearm_id
                    != range_firearm.id
                ):
                    raise ValueError(
                        "Range ammunition record does not belong "
                        "to the selected firearm record."
                    )

                old_source = usage.source_type
                old_lot_id = usage.ammo_lot_id
                old_quantity = usage.quantity

                new_source = ammo_input.source_type
                new_lot_id = (
                    ammo_input.ammo_lot_id
                    if new_source
                    == RangeAmmoSourceType.INVENTORY
                    else None
                )
                new_quantity = ammo_input.quantity

                # Inventory -> same inventory lot.
                if (
                    old_source
                    == RangeAmmoSourceType.INVENTORY
                    and new_source
                    == RangeAmmoSourceType.INVENTORY
                    and old_lot_id == new_lot_id
                ):
                    difference = (
                        new_quantity - old_quantity
                    )

                    if difference > 0:
                        record_correction(
                            lot_id=new_lot_id,
                            transaction_type=(
                                AmmoTransactionType.ADJUSTMENT_OUT
                            ),
                            quantity=difference,
                            usage_id=usage.id,
                        )

                    elif difference < 0:
                        record_correction(
                            lot_id=old_lot_id,
                            transaction_type=(
                                AmmoTransactionType.ADJUSTMENT_IN
                            ),
                            quantity=abs(difference),
                            usage_id=usage.id,
                        )

                # Anything else involving old inventory:
                # restore the old usage first.
                elif (
                    old_source
                    == RangeAmmoSourceType.INVENTORY
                ):
                    if old_lot_id is None:
                        raise ValueError(
                            "Inventory range usage is missing "
                            "its ammunition lot."
                        )

                    record_correction(
                        lot_id=old_lot_id,
                        transaction_type=(
                            AmmoTransactionType.ADJUSTMENT_IN
                        ),
                        quantity=old_quantity,
                        usage_id=usage.id,
                    )

                    if (
                        new_source
                        == RangeAmmoSourceType.INVENTORY
                    ):
                        record_correction(
                            lot_id=new_lot_id,
                            transaction_type=(
                                AmmoTransactionType.ADJUSTMENT_OUT
                            ),
                            quantity=new_quantity,
                            usage_id=usage.id,
                        )

                # Other -> Inventory.
                elif (
                    old_source
                    == RangeAmmoSourceType.OTHER
                    and new_source
                    == RangeAmmoSourceType.INVENTORY
                ):
                    record_correction(
                        lot_id=new_lot_id,
                        transaction_type=(
                            AmmoTransactionType.ADJUSTMENT_OUT
                        ),
                        quantity=new_quantity,
                        usage_id=usage.id,
                    )

                usage.range_session_firearm_id = (
                    range_firearm.id
                )
                usage.source_type = new_source
                usage.ammo_lot_id = new_lot_id
                usage.quantity = new_quantity
                usage.description = description

        range_session.occurred_date = occurred_date
        range_session.location = location
        range_session.notes = notes

        db.add(
            AuditEvent(
                owner_id=owner_id,
                actor_user_id=actor_user_id,
                entity_type="range_session",
                entity_id=range_session.id,
                action="updated",
                changes={
                    "before": old_session_values,
                    "after": {
                        "occurred_date": (
                            occurred_date.isoformat()
                        ),
                        "location": location,
                        "notes": notes,
                    },
                    "firearm_ids": [
                        str(firearm_id)
                        for firearm_id in firearm_ids
                    ],
                    "correction_transaction_ids": (
                        correction_transaction_ids
                    ),
                },
            )
        )

        db.commit()
        db.refresh(range_session)

        return range_session

    except Exception:
        db.rollback()
        raise