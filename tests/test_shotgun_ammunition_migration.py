import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


def revision():
    path = (Path(__file__).resolve().parents[1]
            / "migrations/versions/b61a4e70c2d9_add_shotgun_ammunition.py")
    spec = importlib.util.spec_from_file_location("shotgun_revision", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ShotgunAmmunitionMigrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        self.addCleanup(self.engine.dispose)
        with self.engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE ammo_products (
                    id TEXT PRIMARY KEY,
                    brand_id TEXT NOT NULL,
                    caliber_id TEXT NOT NULL,
                    grain_weight NUMERIC(7, 2),
                    projectile_type VARCHAR(100),
                    product_name VARCHAR(255),
                    manufacturer_sku VARCHAR(100),
                    notes TEXT,
                    created_at DATETIME NOT NULL
                )
            """))
            connection.execute(text("""
                INSERT INTO ammo_products
                    (id, brand_id, caliber_id, created_at)
                VALUES ('legacy', 'brand', 'caliber', CURRENT_TIMESTAMP)
            """))

    def run_revision(self, action):
        module = revision()
        with self.engine.begin() as connection:
            with patch.object(module, "op", Operations(MigrationContext.configure(connection))):
                getattr(module, action)()
        return module

    def test_upgrade_classifies_existing_products_and_enforces_separation(self):
        module = self.run_revision("upgrade")
        self.assertEqual(module.down_revision, "12ef7a4b9c31")
        with self.engine.begin() as connection:
            row = connection.execute(text(
                "SELECT ammunition_type, shell_length_inches FROM ammo_products WHERE id='legacy'"
            )).one()
            self.assertEqual(row, ("rifle_pistol", None))
            connection.execute(text("""
                INSERT INTO ammo_products
                    (id, brand_id, caliber_id, ammunition_type, shell_length_inches,
                     shot_size, shot_type, created_at)
                VALUES ('shotgun', 'brand', 'gauge', 'shotgun', 2.75, '#7½', 'birdshot', CURRENT_TIMESTAMP)
            """))
            with self.assertRaises(IntegrityError):
                connection.execute(text("""
                    INSERT INTO ammo_products
                        (id, brand_id, caliber_id, ammunition_type, grain_weight, created_at)
                    VALUES ('invalid', 'brand', 'gauge', 'shotgun', 55, CURRENT_TIMESTAMP)
                """))
        index_names = {item["name"] for item in inspect(self.engine).get_indexes("ammo_products")}
        self.assertIn("ix_ammo_products_ammunition_type", index_names)

    def test_downgrade_refuses_to_discard_shotgun_records(self):
        module = self.run_revision("upgrade")
        with self.engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO ammo_products
                    (id, brand_id, caliber_id, ammunition_type, created_at)
                VALUES ('shotgun', 'brand', 'gauge', 'shotgun', CURRENT_TIMESTAMP)
            """))
            with patch.object(module, "op", Operations(MigrationContext.configure(connection))):
                with self.assertRaisesRegex(RuntimeError, "shotgun ammunition products"):
                    module.downgrade()

    def test_empty_shotgun_downgrade_keeps_legacy_rows(self):
        module = self.run_revision("upgrade")
        with self.engine.begin() as connection:
            with patch.object(module, "op", Operations(MigrationContext.configure(connection))):
                module.downgrade()
            row = connection.execute(text("SELECT id, grain_weight FROM ammo_products")).one()
            self.assertEqual(row, ("legacy", None))
            self.assertNotIn("ammunition_type", {column["name"] for column in inspect(connection).get_columns("ammo_products")})


if __name__ == "__main__":
    unittest.main()
