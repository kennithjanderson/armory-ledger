import unittest
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

import test_ammo_merging as fixtures
from app.models.ammo_inventory_transaction import AmmoInventoryTransaction, AmmoTransactionType
from app.models.ammo_lot import AmmoLot
from app.models.ammo_product import AmmoProduct
from app.services.ammunition_service import find_duplicate_ammunition_lots


class AmmunitionSuggestionServiceTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.AmmoMergeTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.db = self.f.db
        self.owner = self.f.f.owner
        self.organization_id = self.f.source.ammo_product.brand.manufacturer_id
        self.f.source.ammo_product.grain_weight = 115
        self.f.source.ammo_product.projectile_type = "FMJ"
        self.db.commit()

    def candidates(self, **changes):
        values = dict(
            owner_id=self.owner.id,
            manufacturer_id=self.organization_id,
            caliber_id=self.f.source.ammo_product.caliber_id,
            grain_weight=self.f.source.ammo_product.grain_weight,
            projectile_type=self.f.source.ammo_product.projectile_type,
        )
        values.update(changes)
        return find_duplicate_ammunition_lots(self.db, **values)

    def test_exact_matches_are_owner_scoped_and_zero_balance_is_eligible(self):
        depleted = AmmoLot(
            id=uuid4(), owner_id=self.owner.id,
            ammo_product_id=self.f.source.ammo_product_id,
        )
        self.db.add(depleted)
        self.db.flush()
        self.db.add(AmmoInventoryTransaction(
            ammo_lot_id=depleted.id,
            transaction_type=AmmoTransactionType.ACQUIRED,
            quantity=12,
            occurred_at=datetime.now(timezone.utc),
        ))
        self.db.add(AmmoInventoryTransaction(
            ammo_lot_id=depleted.id,
            transaction_type=AmmoTransactionType.EXPENDED,
            quantity=12,
            occurred_at=datetime.now(timezone.utc),
        ))
        self.db.commit()

        found = dict((lot.id, balance) for lot, balance in self.candidates())
        self.assertEqual(set(found), {self.f.source.id, self.f.destination.id, depleted.id})
        self.assertEqual(found[depleted.id], 0)
        self.assertNotIn(self.f.f.foreign_lot.id, found)

    def test_product_name_and_sku_do_not_override_the_four_match_fields(self):
        original = self.f.source.ammo_product
        other_label = AmmoProduct(
            id=uuid4(), brand_id=original.brand_id, caliber_id=original.caliber_id,
            grain_weight=original.grain_weight, projectile_type=original.projectile_type,
            product_name="Different box label", manufacturer_sku="different-sku",
        )
        self.db.add(other_label)
        self.db.flush()
        lot = AmmoLot(id=uuid4(), owner_id=self.owner.id, ammo_product_id=other_label.id)
        self.db.add(lot)
        self.db.flush()
        self.db.add(AmmoInventoryTransaction(
            ammo_lot_id=lot.id, transaction_type=AmmoTransactionType.ACQUIRED,
            quantity=6, occurred_at=datetime.now(timezone.utc),
        ))
        self.db.commit()
        found = dict((candidate.id, balance) for candidate, balance in self.candidates())
        self.assertEqual(found[lot.id], 6)

    def test_grain_projectile_caliber_and_manufacturer_must_match(self):
        product = self.f.source.ammo_product
        for changes in (
            {"grain_weight": product.grain_weight + 1},
            {"projectile_type": "different projectile"},
            {"caliber_id": self.f.f.rifle_caliber.id},
            {"manufacturer_id": uuid4()},
        ):
            self.assertEqual(self.candidates(**changes), [])
        self.assertEqual(len(self.candidates(projectile_type=f"  {product.projectile_type.upper()}  ")), 2)

    def test_lot_numbers_and_merged_lots_are_excluded(self):
        self.f.source.lot_number = "Maker lot 42"
        self.f.destination.lot_number = "   "
        self.db.commit()
        self.assertEqual([lot.id for lot, _ in self.candidates()], [self.f.destination.id])
        self.f.destination.merged_into_lot_id = self.f.source.id
        self.db.commit()
        self.assertEqual(self.candidates(), [])


if __name__ == "__main__":
    unittest.main()
