import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def revision():
    path = Path(__file__).resolve().parents[1] / "migrations/versions/c7d2a960e148_ammunition_lot_merging.py"
    spec = importlib.util.spec_from_file_location("merge_revision", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MergeMigrationTests(unittest.TestCase):
    def test_upgrade_keeps_legacy_rows_and_empty_downgrade(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        self.addCleanup(engine.dispose)
        module = revision()
        self.assertEqual(module.down_revision, "82c1f947ad30")
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE users (id UUID PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE ammo_lots (id UUID PRIMARY KEY, notes TEXT)"))
            connection.execute(text("CREATE TABLE ammo_inventory_transactions (id UUID PRIMARY KEY, quantity INTEGER)"))
            connection.execute(text("INSERT INTO ammo_lots VALUES ('source', 'Original notes')"))
            connection.execute(text("INSERT INTO ammo_inventory_transactions VALUES ('acquisition', 200)"))
            with patch.object(module, "op", Operations(MigrationContext.configure(connection))):
                module.upgrade()
                self.assertEqual(connection.execute(text("SELECT notes, merged_into_lot_id FROM ammo_lots")).one(),
                                 ("Original notes", None))
                self.assertEqual(connection.execute(text("SELECT quantity, merge_id FROM ammo_inventory_transactions")).one(),
                                 (200, None))
                module.downgrade()
                self.assertEqual(connection.execute(text("SELECT quantity FROM ammo_inventory_transactions")).scalar(), 200)
                self.assertNotIn("ammo_lot_merges", inspect(connection).get_table_names())

    def test_populated_history_blocks_downgrade(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        self.addCleanup(engine.dispose)
        module = revision()
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE ammo_lot_merges (id INTEGER)"))
            connection.execute(text("INSERT INTO ammo_lot_merges VALUES (1)"))
            with patch.object(module, "op", Operations(MigrationContext.configure(connection))):
                with self.assertRaisesRegex(RuntimeError, "merge history"):
                    module.downgrade()
            self.assertEqual(connection.execute(text("SELECT COUNT(*) FROM ammo_lot_merges")).scalar(), 1)

    def test_postgres_upgrade_sql(self):
        output = io.StringIO()
        context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
        module = revision()
        with patch.object(module, "op", Operations(context)):
            module.upgrade()
        sql = output.getvalue()
        self.assertIn("ADD VALUE IF NOT EXISTS 'merge_in'", sql)
        self.assertIn("ADD VALUE IF NOT EXISTS 'merge_out'", sql)
        self.assertIn("CREATE TABLE ammo_lot_merges", sql)
        self.assertIn("UNIQUE (source_lot_id)", sql)
        self.assertNotIn("DELETE FROM", sql)
        self.assertNotIn("UPDATE ammo_inventory_transactions", sql)
