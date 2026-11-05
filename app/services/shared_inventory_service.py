"""Read-only inventory views granted by accepted sharing invitations."""
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.inventory_share import InventoryShare
from app.models.ammo_lot import AmmoLot
from app.models.ammo_product import AmmoProduct
from app.models.firearm import Firearm
from app.models.range_session import RangeSession
from app.models.range_session_ammo_usage import RangeAmmoSourceType, RangeSessionAmmoUsage
from app.models.range_session_firearm import RangeSessionFirearm
from app.models.user import User
from app.services.sharing_service import section_access


def firearm_read_view(firearm):
    """Expose only non-sensitive firearm fields permitted by the RO policy."""
    return SimpleNamespace(
        id=firearm.id,
        model=firearm.model,
        manufacturer=SimpleNamespace(name=firearm.manufacturer.name)
        if firearm.manufacturer else None,
        caliber=SimpleNamespace(name=firearm.caliber.name)
        if firearm.caliber else None,
        firearm_type=firearm.firearm_type,
        status=firearm.status,
    )


def accessory_read_view(accessory, *, owner_id):
    """Expose accessory identity and count without locations or identifiers."""
    firearm = accessory.firearm
    linked_firearm = (
        SimpleNamespace(
            model=firearm.model,
            manufacturer=SimpleNamespace(name=firearm.manufacturer.name)
            if firearm.manufacturer else None,
        )
        if firearm is not None and firearm.owner_id == owner_id
        else None
    )
    return SimpleNamespace(
        id=accessory.id,
        name=accessory.name,
        model=accessory.model,
        quantity=accessory.quantity,
        manufacturer=SimpleNamespace(name=accessory.manufacturer.name)
        if accessory.manufacturer else None,
        firearm=linked_firearm,
    )


def ammunition_read_view(lot):
    """Expose product specifications and lot identity, but no notes/history."""
    product = lot.ammo_product
    manufacturer = product.brand.manufacturer
    return SimpleNamespace(
        id=lot.id,
        lot_number=lot.lot_number,
        ammo_product=SimpleNamespace(
            brand=SimpleNamespace(
                name=product.brand.name,
                manufacturer=SimpleNamespace(name=manufacturer.name),
            ),
            caliber=SimpleNamespace(name=product.caliber.name),
            ammunition_type=product.ammunition_type,
            grain_weight=product.grain_weight,
            projectile_type=product.projectile_type,
            shell_length_inches=product.shell_length_inches,
            shot_size=product.shot_size,
            shot_type=product.shot_type,
            product_name=product.product_name,
            manufacturer_sku=product.manufacturer_sku,
        ),
    )


def accessible_shares(db: Session, *, recipient_id, section: str) -> list[tuple[User, str]]:
    """Return owners whose accepted grant permits viewing one section.

    Effective access is evaluated for every share so section dependencies and
    revocations are applied at request time. Admin status is deliberately not
    consulted.
    """
    shares = db.scalars(
        select(InventoryShare)
        .options(joinedload(InventoryShare.owner))
        .where(
            InventoryShare.recipient_id == recipient_id,
            InventoryShare.status == "accepted",
        )
        .order_by(InventoryShare.created_at, InventoryShare.id)
    ).all()
    result = []
    for share in shares:
        access = section_access(
            db,
            owner_id=share.owner_id,
            actor_id=recipient_id,
            section=section,
        )
        if access != "none" and share.owner is not None:
            result.append((share.owner, access))
    return result


def require_shared_read(db: Session, *, owner_id, actor_id, section: str) -> User:
    """Resolve a shared owner or fail closed without revealing record existence."""
    if owner_id == actor_id or section_access(
        db, owner_id=owner_id, actor_id=actor_id, section=section
    ) == "none":
        raise LookupError("Shared inventory record not found")
    owner = db.get(User, owner_id)
    if owner is None:
        raise LookupError("Shared inventory record not found")
    return owner


def shared_range_session_view(db: Session, *, owner_id, session_id):
    """Build a redacted Shooting Log view; reject any mixed-owner references."""
    views = _shared_range_session_views(
        db, owner_id=owner_id, session_ids=[session_id],
    )
    return views[0] if views else None


def shared_range_sessions(db: Session, *, owner_id):
    """List only sessions safe to expose within a shared owner's log grant."""
    return _shared_range_session_views(db, owner_id=owner_id)


def _shared_range_session_views(db: Session, *, owner_id, session_ids=None):
    session_query = select(RangeSession).where(RangeSession.owner_id == owner_id)
    if session_ids is not None:
        if not session_ids:
            return []
        session_query = session_query.where(RangeSession.id.in_(session_ids))
    sessions = db.scalars(
        session_query.order_by(
            RangeSession.occurred_date.desc(), RangeSession.created_at.desc()
        )
    ).all()
    if not sessions:
        return []
    sessions_by_id = {session.id: session for session in sessions}
    links = db.scalars(
        select(RangeSessionFirearm)
        .options(joinedload(RangeSessionFirearm.firearm).joinedload(Firearm.manufacturer))
        .where(RangeSessionFirearm.range_session_id.in_(sessions_by_id))
        .order_by(RangeSessionFirearm.created_at, RangeSessionFirearm.id)
    ).unique().all()
    links_by_session = {}
    for link in links:
        links_by_session.setdefault(link.range_session_id, []).append(link)
    link_ids = [link.id for link in links]
    usages_by_link = {}
    if link_ids:
        usages = db.scalars(
            select(RangeSessionAmmoUsage)
            .options(
                joinedload(RangeSessionAmmoUsage.ammo_lot)
                .joinedload(AmmoLot.ammo_product)
                .joinedload(AmmoProduct.brand),
                joinedload(RangeSessionAmmoUsage.ammo_lot)
                .joinedload(AmmoLot.ammo_product)
                .joinedload(AmmoProduct.caliber),
            )
            .where(RangeSessionAmmoUsage.range_session_firearm_id.in_(link_ids))
            .order_by(RangeSessionAmmoUsage.created_at, RangeSessionAmmoUsage.id)
        ).unique().all()
        for usage in usages:
            usages_by_link.setdefault(usage.range_session_firearm_id, []).append(usage)

    results = []
    for session in sessions:
        session_links = links_by_session.get(session.id, [])
        if not session_links or any(
            link.firearm is None or link.firearm.owner_id != owner_id
            for link in session_links
        ):
            continue
        firearm_records = []
        total_rounds = 0
        invalid_session = False
        for link in session_links:
            link_usages = usages_by_link.get(link.id, [])
            if any(
                usage.source_type == RangeAmmoSourceType.INVENTORY
                and (usage.ammo_lot is None or usage.ammo_lot.owner_id != owner_id)
                for usage in link_usages
            ):
                invalid_session = True
                break
            total = sum(usage.quantity for usage in link_usages)
            total_rounds += total
            safe_usages = []
            for usage in link_usages:
                safe_lot = None
                if usage.source_type == RangeAmmoSourceType.INVENTORY:
                    safe_lot = ammunition_read_view(usage.ammo_lot)
                safe_usages.append(SimpleNamespace(
                    source_type=usage.source_type,
                    quantity=usage.quantity,
                    ammo_lot=safe_lot,
                ))
            firearm_records.append({
                "firearm": firearm_read_view(link.firearm),
                "rounds": total,
                "ammo_usage": safe_usages,
            })
        if invalid_session:
            continue
        results.append({
            "session": SimpleNamespace(
                id=session.id,
                activity_type=session.activity_type,
                occurred_date=session.occurred_date,
            ),
            "firearm_records": firearm_records,
            "total_rounds": total_rounds,
        })
    return results
