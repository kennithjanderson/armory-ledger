from datetime import date, datetime, timezone
from decimal import Decimal
import unittest
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

import test_range_service as fixtures
from app.models.ammo_brand import AmmoBrand
from app.models.ammo_inventory_transaction import AmmoInventoryTransaction, AmmoTransactionType
from app.models.ammo_lot import AmmoLot
from app.models.ammo_lot_merge import AmmoLotMerge
from app.models.ammo_product import AmmoProduct
from app.models.audit_event import AuditEvent
from app.models.notification import NotificationEvent, NotificationRecipient
from app.models.range_session_ammo_usage import RangeAmmoSourceType, RangeSessionAmmoUsage
from app.services.ammo_inventory_service import record_inventory_activity, lock_owned_lots, shooting_expenditure_descriptions
from app.services.ammo_merge_service import compatible_lots, merge_candidates, merge_lots
from app.services.ammunition_service import update_ammunition
from app.services.range_service import RangeAmmoUsageInput, RangeFirearmInput


class AmmoMergeTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.RangeServiceTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.db = self.f.db
        self.source = self.f.lot
        self.destination = AmmoLot(id=uuid4(), owner_id=self.f.owner.id,
                                   ammo_product_id=self.source.ammo_product_id)
        self.db.add(self.destination)
        self.db.flush()
        for lot, quantity in [(self.source, 100), (self.destination, 200)]:
            self.db.add(AmmoInventoryTransaction(
                ammo_lot_id=lot.id, transaction_type=AmmoTransactionType.ACQUIRED,
                quantity=quantity, occurred_at=datetime.now(timezone.utc),
            ))
        self.db.commit()

    def merge(self, **overrides):
        kwargs = dict(owner_id=self.f.owner.id, source_id=self.source.id,
                      destination_id=self.destination.id, expected_source=200, expected_destination=200)
        kwargs.update(overrides)
        return merge_lots(self.db, **kwargs)

    def test_merge_conserves_balance_and_preserves_acquisitions_and_audits(self):
        original = [(t.id, t.ammo_lot_id, t.quantity, t.occurred_at) for t in
                    self.db.scalars(select(AmmoInventoryTransaction)).all()]
        merge = self.merge()
        self.assertEqual(self.f.balance(self.source), 0)
        self.assertEqual(self.f.balance(self.destination), 400)
        self.assertTrue(self.source.is_merged)
        self.assertFalse(self.destination.is_merged)
        self.assertEqual(self.source.merged_into_lot_id, self.destination.id)
        for id_, lot, qty, when in original:
            row = self.db.get(AmmoInventoryTransaction, id_)
            self.assertEqual((row.ammo_lot_id, row.quantity, row.occurred_at), (lot, qty, when))
        transfers = self.db.scalars(select(AmmoInventoryTransaction).where(
            AmmoInventoryTransaction.merge_id == merge.id)).all()
        self.assertEqual({t.transaction_type for t in transfers},
                         {AmmoTransactionType.MERGE_IN, AmmoTransactionType.MERGE_OUT})
        self.assertEqual([t.quantity for t in transfers], [200, 200])
        self.assertEqual(shooting_expenditure_descriptions(self.db, owner_id=self.f.owner.id,
                         transaction_ids=[t.id for t in transfers]), {})
        audit = self.db.scalars(select(AuditEvent).where(AuditEvent.action.in_(["merge_in", "merge_out"]))).all()
        self.assertEqual(len(audit), 2)
        self.assertEqual({a.entity_id for a in audit}, {self.source.id, self.destination.id})
        self.assertTrue(all(a.changes["merge_id"] == str(merge.id) for a in audit))
        self.assertEqual(merge.actor_user_id, self.f.owner.id)
        self.assertEqual(self.f.total(), 0)

    def test_lot_number_rules(self):
        for left, right, eligible in [(None, None, True), ("A", "A", True),
                                      ("A", "B", False), ("A", None, False),
                                      (None, "A", False), ("A", "a", False)]:
            self.source.lot_number, self.destination.lot_number = left, right
            self.assertEqual(compatible_lots(self.source, self.destination), eligible)
        self.source.lot_number = self.destination.lot_number = "Same"
        self.db.commit()
        self.merge()
        self.assertEqual(self.source.lot_number, "Same")

    def test_specification_mismatches_and_missing_values(self):
        original = self.source.ammo_product
        for field, value in [("caliber_id", self.f.rifle_caliber.id),
                             ("brand_id", uuid4()), ("grain_weight", Decimal("124")),
                             ("projectile_type", "FMJ"), ("product_name", "Target"),
                             ("manufacturer_sku", "123"), ("notes", "Special load")]:
            product = AmmoProduct(brand_id=original.brand_id, caliber_id=original.caliber_id,
                                  grain_weight=original.grain_weight, projectile_type=original.projectile_type,
                                  product_name=original.product_name, manufacturer_sku=original.manufacturer_sku,
                                  notes=original.notes)
            setattr(product, field, value)
            candidate = AmmoLot(id=uuid4(), owner_id=self.source.owner_id, ammo_product=product)
            self.assertFalse(compatible_lots(self.source, candidate), field)
        self.assertFalse(compatible_lots(self.source, self.f.rifle_lot))

    def test_backend_rejects_incompatibility_ownership_and_same_id(self):
        for override, error in [({"destination_id": self.f.rifle_lot.id}, ValueError),
                                ({"destination_id": self.f.foreign_lot.id}, LookupError),
                                ({"source_id": self.f.foreign_lot.id}, LookupError),
                                ({"destination_id": self.source.id}, ValueError)]:
            with self.assertRaises(error):
                self.merge(**override)
        self.assertEqual(self.f.balance(self.source), 200)
        self.destination.lot_number = "Known"
        self.db.commit()
        with self.assertRaises(ValueError):
            self.merge()

    def test_candidates_are_owned_compatible_and_active(self):
        self.assertEqual([lot.id for lot in merge_candidates(self.db, source=self.source)], [self.destination.id])
        self.merge()
        self.assertEqual(merge_candidates(self.db, source=self.source), [])
        self.assertNotIn(self.source.id, [lot.id for lot in merge_candidates(self.db, source=self.destination)])

    def test_repeated_submission_and_stale_review_cannot_duplicate_stock(self):
        with self.assertRaisesRegex(ValueError, "Inventory changed"):
            self.merge(expected_source=199)
        self.merge()
        with self.assertRaises(ValueError):
            self.merge()
        self.assertEqual(self.f.balance(self.destination), 400)
        self.assertEqual(len(self.db.scalars(select(AmmoLotMerge)).all()), 1)

    def test_corrections_survive_merge_without_inflating_recorded_rounds(self):
        session = self.f.create()
        item = self.f.edit_input(session)
        item.ammo_usage[0].quantity = 30
        self.f.update(session, item)
        correction_ids = self.db.scalars(select(AmmoInventoryTransaction.id).where(
            AmmoInventoryTransaction.transaction_type == AmmoTransactionType.ADJUSTMENT_OUT)).all()
        self.merge(expected_source=170)
        self.assertEqual(self.f.total(), 30)
        self.assertEqual(self.f.balance(self.destination), 370)
        self.assertEqual(self.db.scalars(select(AmmoInventoryTransaction.id).where(
            AmmoInventoryTransaction.transaction_type == AmmoTransactionType.ADJUSTMENT_OUT)).all(), correction_ids)

    def test_destination_can_later_merge_without_rewriting_original_source_link(self):
        self.merge()
        third = AmmoLot(id=uuid4(), owner_id=self.f.owner.id, ammo_product_id=self.destination.ammo_product_id)
        self.db.add(third)
        self.db.commit()
        merge_lots(self.db, owner_id=self.f.owner.id, source_id=self.destination.id,
                   destination_id=third.id, expected_source=400, expected_destination=0)
        self.assertEqual(self.source.merged_into_lot_id, self.destination.id)
        self.assertEqual(self.destination.merged_into_lot_id, third.id)
        self.assertEqual(self.f.balance(third), 400)
        with self.assertRaises(ValueError):
            self.merge(source_id=third.id, destination_id=self.source.id, expected_source=400, expected_destination=0)

    def test_failure_rolls_back_merge_lifecycle_transfers_and_audit(self):
        with patch.object(self.db, "commit", side_effect=RuntimeError("injected failure")):
            with self.assertRaises(RuntimeError):
                self.merge()
        self.assertFalse(self.source.is_merged)
        self.assertEqual(self.f.balance(self.source), 200)
        self.assertEqual(self.f.balance(self.destination), 200)
        self.assertEqual(self.db.scalars(select(AmmoLotMerge)).all(), [])
        self.assertEqual(self.db.scalars(select(AuditEvent)).all(), [])

    def test_history_retains_lot_and_counts_but_usage_changes_are_rejected(self):
        session = self.f.create()
        item = self.f.edit_input(session)
        usage_id = item.ammo_usage[0].range_session_ammo_usage_id
        self.merge(expected_source=190)
        self.f.update(session, item)  # Notes/date/classification updates remain possible.
        self.assertEqual(self.db.get(RangeSessionAmmoUsage, usage_id).ammo_lot_id, self.source.id)
        self.assertEqual(self.f.total(), 10)
        self.assertEqual(self.f.balance(self.source), 0)
        for change in ["quantity", "lot", "remove", "firearm"]:
            item = self.f.edit_input(session)
            if change == "quantity":
                item.ammo_usage[0].quantity = 5
            elif change == "lot":
                item.ammo_usage[0].ammo_lot_id = self.destination.id
            elif change == "remove":
                item.ammo_usage = [RangeAmmoUsageInput(RangeAmmoSourceType.OTHER, 10)]
            else:
                item.firearm_id = self.f.rifle.id
            with self.assertRaisesRegex(ValueError, "merged ammunition"):
                self.f.update(session, item)
            self.assertEqual(self.f.balance(self.source), 0)
            self.assertEqual(self.f.balance(self.destination), 390)
        with self.assertRaisesRegex(ValueError, "Merged ammunition"):
            self.f.create()

    def test_merged_source_rejects_manual_activity_and_metadata_changes(self):
        self.merge()
        for kind in [AmmoTransactionType.ACQUIRED, AmmoTransactionType.ADJUSTMENT_IN, AmmoTransactionType.EXPENDED]:
            with self.assertRaises(ValueError):
                record_inventory_activity(self.db, lot_id=self.source.id, owner_id=self.f.owner.id,
                    actor_user_id=self.f.owner.id, transaction_type=kind, quantity=1, occurred_date=date.today())
        with self.assertRaises(ValueError):
            update_ammunition(self.db, lot_id=self.source.id, owner_id=self.f.owner.id,
                actor_user_id=self.f.owner.id, caliber_id=self.f.nine.id, grain_weight=None,
                projectile_type=None, product_name=None, manufacturer_sku=None, lot_number=None,
                notes=None, acquired_date=None)
        for kind in [AmmoTransactionType.MERGE_IN, AmmoTransactionType.MERGE_OUT]:
            with self.assertRaisesRegex(ValueError, "Invalid inventory"):
                record_inventory_activity(self.db, lot_id=self.destination.id, owner_id=self.f.owner.id,
                    actor_user_id=self.f.owner.id, transaction_type=kind, quantity=1, occurred_date=date.today())

    def test_low_inventory_crossing_rearms_and_stays_private_to_lot_owner(self):
        self.f.owner.ammo_notifications_in_app = True
        self.source.low_inventory_notifications_enabled = True
        self.source.low_inventory_threshold = 50
        self.db.commit()
        def activity(kind, quantity):
            return record_inventory_activity(
                self.db, lot_id=self.source.id, owner_id=self.f.owner.id,
                actor_user_id=self.f.owner.id, transaction_type=kind,
                quantity=quantity, occurred_date=date.today(),
            )

        activity(AmmoTransactionType.EXPENDED, 151)  # 200 -> 49
        activity(AmmoTransactionType.EXPENDED, 1)    # Still below: no repeat.
        events = self.db.scalars(select(NotificationEvent)).all()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, "ammo_low_inventory")
        self.assertIn("50-round threshold", events[0].message)
        self.assertIn("49 rounds", events[0].message)
        self.assertEqual(events[0].scope, "user")
        self.assertEqual(events[0].severity, "info")

        activity(AmmoTransactionType.ACQUIRED, 20)   # 48 -> 68 rearms.
        activity(AmmoTransactionType.EXPENDED, 20)   # 68 -> 48 alerts again.
        events = self.db.scalars(select(NotificationEvent).order_by(NotificationEvent.created_at)).all()
        self.assertEqual(len(events), 2)
        recipients = self.db.scalars(select(NotificationRecipient)).all()
        self.assertEqual(len(recipients), 2)
        self.assertEqual({row.user_id for row in recipients}, {self.f.owner.id})
        from app.services.notification_service import notices
        self.f.other.is_admin = True
        self.assertEqual(notices(self.db, self.f.other)["items"], [])

    def test_email_only_preference_queues_existing_outbox_without_in_app_copy(self):
        self.f.owner.ammo_notifications_email = True
        self.source.depleted_notifications_enabled = True
        self.db.commit()
        from app.services import notification_service
        with patch.object(notification_service, "mail_config", return_value={"enabled": True}):
            record_inventory_activity(
                self.db, lot_id=self.source.id, owner_id=self.f.owner.id,
                actor_user_id=self.f.owner.id, transaction_type=AmmoTransactionType.EXPENDED,
                quantity=200, occurred_date=date.today(),
            )
        recipient = self.db.scalars(select(NotificationRecipient)).one()
        self.assertFalse(recipient.in_app)
        self.assertEqual(recipient.email_state, "pending")

    def test_lock_query_orders_rows_and_refreshes_identity_map(self):
        statements = []
        original = self.db.scalars
        def capture(statement, *args, **kwargs):
            statements.append(statement)
            return original(statement, *args, **kwargs)
        with patch.object(self.db, "scalars", side_effect=capture):
            lock_owned_lots(self.db, owner_id=self.f.owner.id, lot_ids=[self.source.id, self.destination.id])
        sql = str(statements[0].compile(dialect=postgresql.dialect()))
        self.assertIn("ORDER BY ammo_lots.id FOR UPDATE", sql)
        self.assertTrue(statements[0].get_execution_options()["populate_existing"])
