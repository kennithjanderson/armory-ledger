from datetime import date
import unittest

from sqlalchemy import select

import test_range_service as fixtures
from app.models.ammo_inventory_transaction import AmmoInventoryTransaction, AmmoTransactionType
from app.models.audit_event import AuditEvent
from app.models.range_session import ShootingActivityType
from app.models.range_session_ammo_usage import RangeAmmoSourceType, RangeSessionAmmoUsage
from app.services.ammo_inventory_service import record_inventory_activity, shooting_expenditure_descriptions
from app.services.range_service import RangeAmmoUsageInput, RangeFirearmInput


class ExpenditureDescriptionTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.RangeServiceTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.db = self.f.db

    def descriptions(self, owner=None):
        return shooting_expenditure_descriptions(self.db, owner_id=owner or self.f.owner.id,
            transaction_ids=self.db.scalars(select(AmmoInventoryTransaction.id)).all())

    def test_each_activity_description_and_type_edits_preserve_ledger(self):
        session = self.f.create()
        usage = self.db.scalar(select(RangeSessionAmmoUsage))
        transaction = self.db.get(AmmoInventoryTransaction, usage.inventory_transaction_id)
        original_notes = transaction.notes
        ids = self.db.scalars(select(AmmoInventoryTransaction.id)).all()
        audit = self.db.scalar(select(AuditEvent).where(AuditEvent.action == "inventory_activity"))
        original_audit = dict(audit.changes)
        expected = ["Range session expenditure.", "Hunting expenditure.", "Training expenditure.",
                    "Defensive action expenditure.", "Other shooting activity expenditure."]
        for activity, description in zip(ShootingActivityType, expected):
            self.f.update(session, self.f.edit_input(session), activity_type=activity)
            self.assertEqual(self.descriptions()[transaction.id], description)
            self.assertEqual(self.f.balance(self.f.lot), 90)
            self.assertEqual(self.f.total(), 10)
            self.assertEqual(transaction.notes, original_notes)
            self.assertEqual(audit.changes, original_audit)
        self.assertEqual(self.db.scalars(select(AmmoInventoryTransaction.id)).all(), ids)
        self.assertEqual(self.descriptions(owner=self.f.other.id), {})

    def test_new_expenditures_store_correct_activity_for_multiple_firearms_rows(self):
        self.f.create([
            RangeFirearmInput(self.f.firearm.id, ammo_usage=[self.f.ammo(), self.f.ammo()]),
            RangeFirearmInput(self.f.rifle.id, ammo_usage=[self.f.ammo(self.f.rifle_lot)]),
        ], activity_type=ShootingActivityType.HUNTING)
        transactions = self.db.scalars(select(AmmoInventoryTransaction).where(
            AmmoInventoryTransaction.transaction_type == AmmoTransactionType.EXPENDED)).all()
        self.assertEqual(len(transactions), 3)
        self.assertTrue(all(t.notes == "Hunting expenditure." for t in transactions))
        self.assertEqual(set(self.descriptions().values()), {"Hunting expenditure."})

    def test_unlinked_manual_acquisitions_and_corrections_preserve_text(self):
        manual = record_inventory_activity(self.db, lot_id=self.f.lot.id,
            owner_id=self.f.owner.id, actor_user_id=self.f.owner.id,
            transaction_type=AmmoTransactionType.EXPENDED, quantity=1,
            occurred_date=date.today(), notes="Manual expenditure")
        session = self.f.create()
        item = self.f.edit_input(session)
        original_usage = self.db.get(RangeSessionAmmoUsage, item.ammo_usage[0].range_session_ammo_usage_id)
        expenditure_id = original_usage.inventory_transaction_id
        item.ammo_usage = [RangeAmmoUsageInput(RangeAmmoSourceType.OTHER, 10)]
        self.f.update(session, item, activity_type=ShootingActivityType.TRAINING)
        # Removed usage loses its reliable link; keep the stored original description.
        self.assertNotIn(expenditure_id, self.descriptions())
        self.assertNotIn(manual.id, self.descriptions())
        self.assertEqual(manual.notes, "Manual expenditure")
        self.assertEqual(self.db.get(AmmoInventoryTransaction, expenditure_id).notes, "Range session expenditure.")
        for tx in self.db.scalars(select(AmmoInventoryTransaction)):
            if tx.transaction_type != AmmoTransactionType.EXPENDED:
                self.assertNotIn(tx.id, self.descriptions())

    def test_new_row_on_edit_uses_updated_classification(self):
        session = self.f.create()
        item = self.f.edit_input(session)
        item.ammo_usage.append(self.f.ammo())
        self.f.update(session, item, activity_type=ShootingActivityType.DEFENSIVE)
        descriptions = self.descriptions()
        self.assertEqual(len(descriptions), 2)
        self.assertEqual(set(descriptions.values()), {"Defensive action expenditure."})
        self.assertEqual(self.f.balance(self.f.lot), 80)
