import unittest
from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from pydantic import ValidationError

import test_ammo_merging as fixtures
from app.models.ammo_product import AmmoProduct
from app.models.ammo_inventory_transaction import AmmoInventoryTransaction
from app.models.audit_event import AuditEvent
from app.models.organization import ManufacturerProfile
from app.api.ammunition import AmmunitionAcquisitionRequest, AmmunitionUpdateRequest
from app.services.ammo_inventory_service import get_physical_inventory
from app.services.ammo_merge_service import compatible_lots
from app.services.ammunition_service import (
    acquire_ammunition,
    find_duplicate_ammunition_lots,
    update_ammunition,
)


class ShotgunAmmunitionServiceTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.AmmoMergeTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.db = self.f.db
        self.owner = self.f.f.owner
        self.manufacturer_id = self.f.source.ammo_product.brand.manufacturer_id
        self.caliber_id = self.f.source.ammo_product.caliber_id
        self.db.add(ManufacturerProfile(organization_id=self.manufacturer_id))
        self.db.commit()

    def acquire(self, **overrides):
        values = dict(
            db=self.db,
            owner_id=self.owner.id,
            manufacturer_id=self.manufacturer_id,
            caliber_id=self.caliber_id,
            ammunition_type="shotgun",
            grain_weight=None,
            projectile_type=None,
            shell_length_inches=Decimal("2.75"),
            shot_size="#7½",
            shot_type="Birdshot",
            quantity=25,
            acquired_date=date(2026, 11, 5),
        )
        values.update(overrides)
        db = values.pop("db")
        return acquire_ammunition(db, **values)

    def test_acquisition_suggestions_and_inventory_use_shotgun_specs(self):
        lot = self.acquire()
        product = lot.ammo_product
        self.assertEqual(product.ammunition_type, "shotgun")
        self.assertEqual(product.shell_length_inches, Decimal("2.75"))
        self.assertEqual(product.shot_size, "#7½")
        self.assertEqual(product.shot_type, "Birdshot")
        self.assertIsNone(product.grain_weight)
        self.assertIsNone(product.projectile_type)
        self.assertEqual(get_physical_inventory(self.db, lot_id=lot.id), 25)

        matches = find_duplicate_ammunition_lots(
            self.db,
            owner_id=self.owner.id,
            manufacturer_id=self.manufacturer_id,
            caliber_id=self.caliber_id,
            ammunition_type="shotgun",
            grain_weight=None,
            projectile_type=None,
            shell_length_inches=Decimal("2.75"),
            shot_size=" #7½ ",
            shot_type="birdshot",
        )
        self.assertEqual([candidate.id for candidate, _ in matches], [lot.id])
        other_shotgun_spec = find_duplicate_ammunition_lots(
            self.db,
            owner_id=self.owner.id,
            manufacturer_id=self.manufacturer_id,
            caliber_id=self.caliber_id,
            ammunition_type="shotgun",
            grain_weight=None,
            projectile_type=None,
            shell_length_inches=Decimal("2.75"),
            shot_size="#8",
            shot_type="Birdshot",
        )
        self.assertNotIn(lot.id, [candidate.id for candidate, _ in other_shotgun_spec])

    def test_specifications_cannot_mix_between_categories(self):
        with self.assertRaisesRegex(ValueError, "only valid for Rifle/Pistol"):
            self.acquire(grain_weight=Decimal("55"))
        with self.assertRaisesRegex(ValueError, "only valid for shotgun"):
            self.acquire(ammunition_type="rifle_pistol", shell_length_inches=Decimal("2.75"))
        with self.assertRaisesRegex(ValueError, "two decimal places"):
            self.acquire(shell_length_inches=Decimal("2.755"))

    def test_request_validation_defaults_legacy_payloads_and_rejects_mixed_specs(self):
        common = {
            "manufacturer_id": str(self.manufacturer_id),
            "caliber_id": str(self.caliber_id),
            "quantity": 1,
            "acquired_date": "2026-11-05",
        }
        legacy = AmmunitionAcquisitionRequest.model_validate(common)
        self.assertEqual(legacy.ammunition_type, "rifle_pistol")
        shotgun = AmmunitionAcquisitionRequest.model_validate({
            **common,
            "ammunition_type": "shotgun",
            "shell_length_inches": "2.75",
            "shot_size": "00",
            "shot_type": "Buckshot",
        })
        self.assertEqual(shotgun.shell_length_inches, Decimal("2.75"))
        with self.assertRaises(ValidationError):
            AmmunitionAcquisitionRequest.model_validate({
                **common,
                "ammunition_type": "shotgun",
                "grain_weight": 55,
            })
        with self.assertRaises(ValidationError):
            AmmunitionUpdateRequest.model_validate({
                "caliber_id": str(self.caliber_id),
                "ammunition_type": "rifle_pistol",
                "shell_length_inches": "2.75",
            })

    def test_edit_records_spec_changes_without_changing_inventory_history(self):
        lot = self.acquire()
        transactions_before = len(self.db.scalars(select(AmmoInventoryTransaction).where(
            AmmoInventoryTransaction.ammo_lot_id == lot.id
        )).all())
        updated = update_ammunition(
            self.db,
            lot_id=lot.id,
            owner_id=self.owner.id,
            actor_user_id=self.owner.id,
            caliber_id=self.caliber_id,
            ammunition_type="shotgun",
            grain_weight=None,
            projectile_type=None,
            shell_length_inches=Decimal("3.00"),
            shot_size="00",
            shot_type="Buckshot",
            product_name=None,
            manufacturer_sku=None,
            lot_number=None,
            notes=None,
            acquired_date=None,
        )
        self.assertEqual(updated.ammo_product.shell_length_inches, Decimal("3.00"))
        self.assertEqual(updated.ammo_product.shot_size, "00")
        self.assertEqual(updated.ammo_product.shot_type, "Buckshot")
        self.assertEqual(get_physical_inventory(self.db, lot_id=lot.id), 25)
        self.assertEqual(len(self.db.scalars(select(AmmoInventoryTransaction).where(
            AmmoInventoryTransaction.ammo_lot_id == lot.id
        )).all()), transactions_before)
        audit = self.db.scalar(select(AuditEvent).where(AuditEvent.entity_id == lot.id))
        self.assertIn("shell_length_inches", audit.changes)
        self.assertIn("shot_size", audit.changes)

    def test_merge_compatibility_includes_type_and_shot_specs(self):
        shotgun = self.acquire()
        rifle_product = self.f.source.ammo_product
        rifle_product.grain_weight = None
        rifle_product.projectile_type = None
        self.db.commit()
        self.assertFalse(compatible_lots(self.f.source, shotgun))

        same_specs = AmmoProduct(
            brand_id=shotgun.ammo_product.brand_id,
            caliber_id=shotgun.ammo_product.caliber_id,
            ammunition_type="shotgun",
            shell_length_inches=Decimal("2.75"),
            shot_size="#7½",
            shot_type="Birdshot",
        )
        self.db.add(same_specs)
        self.db.flush()
        same_lot = type(shotgun)(owner_id=shotgun.owner_id, ammo_product_id=same_specs.id)
        self.db.add(same_lot)
        self.db.flush()
        self.assertTrue(compatible_lots(shotgun, same_lot))
        same_specs.shot_type = "Slug"
        self.assertFalse(compatible_lots(shotgun, same_lot))


if __name__ == "__main__":
    unittest.main()
