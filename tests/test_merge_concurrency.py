"""Opt-in only: requires an explicitly authorized disposable PostgreSQL DB.

Creates/drops only its own random test schema. Never reads application Settings.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import os
from threading import Barrier
import unittest
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import test_ammo_merging as fixtures
import test_range_service as range_fixtures
from app.models.ammo_inventory_transaction import AmmoTransactionType
from app.services.ammo_inventory_service import get_physical_inventory, record_inventory_activity
from app.services.ammo_merge_service import merge_lots

AUTHORIZED = os.environ.get("ARMORY_DISPOSABLE_POSTGRES") == "1" and bool(os.environ.get("ARMORY_TEST_POSTGRES_URL"))


@unittest.skipUnless(AUTHORIZED, "Requires explicitly authorized disposable PostgreSQL; SQLite cannot test row locking")
class MergeConcurrencyTests(unittest.TestCase):
    def setUp(self):
        url = os.environ["ARMORY_TEST_POSTGRES_URL"]
        schema = "armory_merge_test_" + uuid4().hex
        admin = create_engine(url)
        self.addCleanup(admin.dispose)
        with admin.begin() as db:
            db.execute(text(f'CREATE SCHEMA "{schema}"'))
        def cleanup():
            with admin.begin() as db:
                db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        self.addCleanup(cleanup)
        self.engine = create_engine(url, connect_args={"options": f"-csearch_path={schema} -clock_timeout=5000 -cstatement_timeout=10000"})
        self.fixture = fixtures.AmmoMergeTests()
        self.addCleanup(self.fixture.doCleanups)
        with patch.object(range_fixtures.RangeServiceTests, "make_engine", return_value=self.engine):
            self.fixture.setUp()
        self.owner_id = self.fixture.f.owner.id
        self.source_id = self.fixture.source.id
        self.destination_id = self.fixture.destination.id
        self.fixture.db.close()

    def merge(self, barrier):
        with Session(self.engine, autoflush=False) as db:
            barrier.wait(timeout=10)
            try:
                merge_lots(db, owner_id=self.owner_id, source_id=self.source_id,
                           destination_id=self.destination_id, expected_source=200, expected_destination=200)
                return "merged"
            except ValueError:
                return "rejected"

    def balances(self):
        with Session(self.engine) as db:
            return (get_physical_inventory(db, lot_id=self.source_id),
                    get_physical_inventory(db, lot_id=self.destination_id))

    def test_concurrent_duplicate_merge_transfers_once(self):
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.merge, barrier) for _ in range(2)]
            results = [future.result(timeout=15) for future in futures]
        self.assertCountEqual(results, ["merged", "rejected"])
        self.assertEqual(self.balances(), (0, 400))

    def test_concurrent_expenditure_and_merge_cannot_overdraw(self):
        barrier = Barrier(2)
        def expend():
            with Session(self.engine, autoflush=False) as db:
                barrier.wait(timeout=10)
                try:
                    record_inventory_activity(db, owner_id=self.owner_id, actor_user_id=self.owner_id,
                        lot_id=self.source_id, transaction_type=AmmoTransactionType.EXPENDED,
                        quantity=50, occurred_date=date.today())
                    return "expended"
                except ValueError:
                    db.rollback()
                    return "rejected"
        with ThreadPoolExecutor(max_workers=2) as pool:
            merger = pool.submit(self.merge, barrier)
            expenditure = pool.submit(expend)
            result = (merger.result(timeout=15), expenditure.result(timeout=15))
        self.assertIn(result, [("merged", "rejected"), ("rejected", "expended")])
        self.assertIn(self.balances(), [(0, 400), (150, 200)])
