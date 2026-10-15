"""Service regression tests using synthetic SQLite memory data, never app settings.

SQLite substitutes JSON for JSONB and REGEXP for PostgreSQL's regex operator.
These tests exercise service transactions, not PostgreSQL migrations/concurrency.
"""
import unittest
from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, MetaData, create_engine, event, select, text
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.user import User
from app.models.organization import Organization
from app.models.caliber import Caliber
from app.models.firearm import Firearm
from app.models.ammo_brand import AmmoBrand
from app.models.ammo_product import AmmoProduct
from app.models.ammo_lot import AmmoLot
from app.models.ammo_inventory_transaction import AmmoInventoryTransaction, AmmoTransactionType
from app.models.range_session import RangeSession, ShootingActivityType
from app.models.range_session_firearm import RangeSessionFirearm
from app.models.range_session_ammo_usage import RangeSessionAmmoUsage, RangeAmmoSourceType
from app.services.ammo_inventory_service import get_physical_inventory
from app.services.range_service import (
    RangeAmmoUsageInput, RangeFirearmInput, create_range_session, update_range_session,
    get_firearm_recorded_rounds,
)


class RangeServiceTests(unittest.TestCase):
    def make_engine(self):
        return create_engine("sqlite+pysqlite:///:memory:")

    def setUp(self):
        self.engine = self.make_engine()
        if self.engine.dialect.name == "sqlite":
            @event.listens_for(self.engine, "connect")
            def foreign_keys(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")

        # Copy metadata: never modify application models or load a database URL.
        metadata = MetaData()
        for table in Base.metadata.sorted_tables:
            table.to_metadata(metadata)
        if self.engine.dialect.name == "sqlite":
            metadata.tables["audit_events"].c.changes.type = JSON()
            for constraint in metadata.tables["firearms"].constraints:
                if constraint.name == "ck_firearms_purchase_price_currency":
                    constraint.sqltext = text(str(constraint.sqltext).replace(" ~ ", " REGEXP "))
        metadata.create_all(self.engine)
        self.db = Session(self.engine, autoflush=False)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.owner = User(id=uuid4(), oidc_subject="owner", email="owner@example.test", display_name="Owner")
        self.other = User(id=uuid4(), oidc_subject="other", email="other@example.test", display_name="Other")
        self.nine = Caliber(id=uuid4(), name="9mm Luger")
        self.rifle_caliber = Caliber(id=uuid4(), name="5.56 NATO")
        org = Organization(id=uuid4(), name="Test maker")
        self.db.add_all([self.owner, self.other, self.nine, self.rifle_caliber, org])
        self.db.flush()
        brand = AmmoBrand(id=uuid4(), manufacturer_id=org.id, name="Test brand")
        self.db.add(brand)
        self.db.flush()
        self.firearm = Firearm(id=uuid4(), owner_id=self.owner.id, model="Canik", caliber_id=self.nine.id)
        self.rifle = Firearm(id=uuid4(), owner_id=self.owner.id, model="Rifle", caliber_id=self.rifle_caliber.id)
        self.foreign_firearm = Firearm(id=uuid4(), owner_id=self.other.id, model="Private", caliber_id=self.nine.id)
        self.db.add_all([self.firearm, self.rifle, self.foreign_firearm])
        products = [AmmoProduct(id=uuid4(), brand_id=brand.id, caliber_id=c.id)
                    for c in [self.nine, self.rifle_caliber]]
        self.db.add_all(products)
        self.db.flush()
        self.lot = AmmoLot(id=uuid4(), owner_id=self.owner.id, ammo_product_id=products[0].id)
        self.rifle_lot = AmmoLot(id=uuid4(), owner_id=self.owner.id, ammo_product_id=products[1].id)
        self.foreign_lot = AmmoLot(id=uuid4(), owner_id=self.other.id, ammo_product_id=products[0].id)
        self.db.add_all([self.lot, self.rifle_lot, self.foreign_lot])
        self.db.flush()
        for lot in [self.lot, self.rifle_lot, self.foreign_lot]:
            self.db.add(AmmoInventoryTransaction(
                ammo_lot_id=lot.id, transaction_type=AmmoTransactionType.ACQUIRED,
                quantity=100, occurred_at=datetime.now(timezone.utc),
            ))
        self.db.commit()

    def ammo(self, lot=None, quantity=10):
        return RangeAmmoUsageInput(
            source_type=RangeAmmoSourceType.INVENTORY, quantity=quantity,
            ammo_lot_id=(lot or self.lot).id,
        )

    def create(self, firearms=None, **kwargs):
        return create_range_session(
            self.db, owner_id=self.owner.id, actor_user_id=self.owner.id,
            occurred_date=date(2026, 10, 1), location=None, notes=None,
            firearms=firearms or [RangeFirearmInput(self.firearm.id, ammo_usage=[self.ammo()])],
            **kwargs,
        )

    def edit_input(self, session):
        association = self.db.scalar(select(RangeSessionFirearm).where(
            RangeSessionFirearm.range_session_id == session.id))
        usage = self.db.scalar(select(RangeSessionAmmoUsage).where(
            RangeSessionAmmoUsage.range_session_firearm_id == association.id))
        return RangeFirearmInput(
            association.firearm_id, range_session_firearm_id=association.id,
            ammo_usage=[RangeAmmoUsageInput(
                usage.source_type, usage.quantity, ammo_lot_id=usage.ammo_lot_id,
                range_session_ammo_usage_id=usage.id,
            )],
        )

    def update(self, session, item, owner=None, **kwargs):
        return update_range_session(
            self.db, range_session_id=session.id, owner_id=owner or self.owner.id,
            actor_user_id=owner or self.owner.id, occurred_date=session.occurred_date,
            location="Updated location", notes="Updated notes", firearms=[item],
            **kwargs,
        )

    def balance(self, lot):
        return get_physical_inventory(self.db, lot_id=lot.id)

    def test_multiple_firearms_rows_and_recorded_deductions(self):
        session = self.create([
            RangeFirearmInput(self.firearm.id, ammo_usage=[self.ammo(quantity=10), self.ammo(quantity=20)]),
            RangeFirearmInput(self.rifle.id, ammo_usage=[self.ammo(self.rifle_lot, 40)]),
        ])
        self.assertEqual(self.balance(self.lot), 70)
        self.assertEqual(self.balance(self.rifle_lot), 60)
        usages = self.db.scalars(select(RangeSessionAmmoUsage)).all()
        self.assertEqual(sorted(u.quantity for u in usages), [10, 20, 40])
        self.assertTrue(all(u.inventory_transaction_id for u in usages))
        self.assertEqual(session.owner_id, self.owner.id)

    def test_mismatch_rolls_back_whole_create(self):
        with self.assertRaisesRegex(ValueError, "recorded caliber"):
            self.create([RangeFirearmInput(self.firearm.id, ammo_usage=[
                self.ammo(), self.ammo(self.rifle_lot),
            ])])
        self.assertEqual(self.balance(self.lot), 100)
        self.assertEqual(self.db.scalars(select(RangeSession)).all(), [])
        self.assertEqual(self.db.scalars(select(RangeSessionAmmoUsage)).all(), [])

    def test_rifle_rejects_nine_mm(self):
        with self.assertRaises(ValueError):
            self.create([RangeFirearmInput(self.rifle.id, ammo_usage=[self.ammo()])])

    def test_missing_caliber_rejects_inventory_but_allows_other(self):
        self.firearm.caliber_id = None
        self.db.commit()
        with self.assertRaises(ValueError):
            self.create()
        self.create([RangeFirearmInput(self.firearm.id, ammo_usage=[
            RangeAmmoUsageInput(RangeAmmoSourceType.OTHER, 20, description="Borrowed"),
        ])])
        self.assertEqual(self.balance(self.lot), 100)
        usage = self.db.scalar(select(RangeSessionAmmoUsage))
        self.assertIsNone(usage.inventory_transaction_id)

    def test_foreign_lot_and_firearm_rejected(self):
        for item in [RangeFirearmInput(self.firearm.id, ammo_usage=[self.ammo(self.foreign_lot)]),
                     RangeFirearmInput(self.foreign_firearm.id, ammo_usage=[self.ammo()])]:
            with self.assertRaises(LookupError):
                self.create([item])
        self.assertEqual(self.balance(self.foreign_lot), 100)

    def test_total_quantity_limit_and_rollback(self):
        with self.assertRaisesRegex(ValueError, "Only 40"):
            self.create([RangeFirearmInput(self.firearm.id, ammo_usage=[
                self.ammo(quantity=60), self.ammo(quantity=50),
            ])])
        self.assertEqual(self.balance(self.lot), 100)

    def test_edit_quantity_corrections_and_other_transition(self):
        session = self.create()
        item = self.edit_input(session)
        item.ammo_usage[0].quantity = 25
        self.update(session, item)
        self.assertEqual(self.balance(self.lot), 75)
        item.ammo_usage[0].quantity = 5
        self.update(session, item)
        self.assertEqual(self.balance(self.lot), 95)
        item.ammo_usage[0].source_type = RangeAmmoSourceType.OTHER
        item.ammo_usage[0].ammo_lot_id = None
        self.update(session, item)
        self.assertEqual(self.balance(self.lot), 100)

    def test_changed_and_new_mismatched_rows_rejected_on_edit(self):
        session = self.create()
        for new_row in [False, True]:
            item = self.edit_input(session)
            if new_row:
                item.ammo_usage.append(self.ammo(self.rifle_lot))
            else:
                item.ammo_usage[0].ammo_lot_id = self.rifle_lot.id
            with self.assertRaises(ValueError):
                self.update(session, item)
        self.assertEqual(self.balance(self.lot), 90)
        self.assertEqual(self.balance(self.rifle_lot), 100)

    def test_unchanged_history_allowed_but_changed_quantity_or_firearm_rejected(self):
        session = self.create()
        # Simulate a later firearm caliber correction; no historical rewrite.
        self.firearm.caliber_id = None
        self.db.commit()
        item = self.edit_input(session)
        self.update(session, item)
        self.assertEqual(self.balance(self.lot), 90)
        item.ammo_usage[0].quantity = 11
        with self.assertRaises(ValueError):
            self.update(session, item)
        item = self.edit_input(session)
        item.firearm_id = self.rifle.id
        with self.assertRaises(ValueError):
            self.update(session, item)
        self.assertEqual(self.balance(self.lot), 90)

    def test_other_user_cannot_edit_session(self):
        session = self.create()
        with self.assertRaises(LookupError):
            self.update(session, self.edit_input(session), owner=self.other.id)

    def total(self, firearm=None, owner=None):
        return get_firearm_recorded_rounds(
            self.db, owner_id=owner or self.owner.id,
            firearm_id=(firearm or self.firearm).id,
        )

    def test_activity_defaults_and_all_types_inventory_integrity(self):
        self.assertEqual(self.total(), 0)
        self.assertEqual(self.create().activity_type, ShootingActivityType.RANGE)
        for activity_type in ShootingActivityType:
            session = self.create(activity_type=activity_type)
            self.db.expire(session)
            self.assertEqual(session.activity_type, activity_type)
        self.assertEqual(self.balance(self.lot), 40)
        self.assertEqual(self.total(), 60)

    def test_invalid_activity_type_rejected_without_deduction(self):
        with self.assertRaises(ValueError):
            self.create(activity_type="invalid")
        self.assertEqual(self.balance(self.lot), 100)
        session = self.create()
        with self.assertRaises(ValueError):
            self.update(session, self.edit_input(session), activity_type="invalid")
        self.assertEqual(self.total(), 10)

    def test_type_only_edit_preserves_rows_and_inventory(self):
        session = self.create()
        item = self.edit_input(session)
        transactions = self.db.scalars(select(AmmoInventoryTransaction.id)).all()
        for activity_type in ShootingActivityType:
            self.update(session, item, activity_type=activity_type)
            self.assertEqual(session.activity_type, activity_type)
            self.assertEqual(self.edit_input(session), item)
            self.assertEqual(self.balance(self.lot), 90)
            self.assertEqual(self.total(), 10)
        self.assertEqual(self.db.scalars(select(AmmoInventoryTransaction.id)).all(), transactions)
        self.update(session, item)  # Older clients omitting classification retain it.
        self.assertEqual(session.activity_type, ShootingActivityType.OTHER)

    def test_totals_multiple_rows_firearms_external_and_owner_isolation(self):
        session = self.create([
            RangeFirearmInput(self.firearm.id, ammo_usage=[self.ammo(quantity=19),
                RangeAmmoUsageInput(RangeAmmoSourceType.OTHER, 299)]),
            RangeFirearmInput(self.rifle.id, ammo_usage=[self.ammo(self.rifle_lot, 7)]),
        ], activity_type=ShootingActivityType.TRAINING)
        self.assertEqual(self.total(), 318)
        self.assertEqual(self.total(self.rifle), 7)
        self.create([RangeFirearmInput(self.firearm.id, ammo_usage=[
            RangeAmmoUsageInput(RangeAmmoSourceType.OTHER, 3),
        ])], activity_type=ShootingActivityType.HUNTING)
        self.assertEqual(self.total(), 321)
        self.assertEqual(self.total(owner=self.other.id), 0)
        self.assertEqual(self.total(self.foreign_firearm), 0)
        self.assertEqual(self.balance(self.lot), 81)
        self.assertIsNotNone(session.id)

    def test_totals_follow_usage_corrections_and_removed_rows(self):
        session = self.create()
        item = self.edit_input(session)
        item.ammo_usage[0].quantity = 30
        self.update(session, item)
        self.assertEqual(self.total(), 30)  # Original + adjustment must not be added.
        item.ammo_usage.append(RangeAmmoUsageInput(RangeAmmoSourceType.OTHER, 5))
        self.update(session, item)
        self.assertEqual(self.total(), 35)
        usage = self.db.scalar(select(RangeSessionAmmoUsage).where(
            RangeSessionAmmoUsage.source_type == RangeAmmoSourceType.OTHER))
        item.ammo_usage = [RangeAmmoUsageInput(
            RangeAmmoSourceType.OTHER, 5, range_session_ammo_usage_id=usage.id,
        )]
        self.update(session, item)
        self.assertEqual(self.total(), 5)
        self.assertEqual(self.balance(self.lot), 100)


if __name__ == "__main__":
    unittest.main()
