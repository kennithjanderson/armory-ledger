"""Verify the canonical-reference rename audit migration safely."""
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations/versions/480378f66895_reference_name_audit.py"


def load_migration():
    spec = importlib.util.spec_from_file_location("reference_name_audit_migration", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReferenceRenameMigrationTests(unittest.TestCase):
    def test_revision_follows_caliber_alias_administration(self):
        migration = load_migration()
        self.assertEqual(migration.revision, "480378f66895")
        self.assertEqual(migration.down_revision, "e8a1f3c0d64b")

    def test_upgrade_and_empty_downgrade_preserve_existing_schema(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        self.addCleanup(engine.dispose)
        migration = load_migration()
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE users (id UUID PRIMARY KEY)"))
            with patch.object(migration, "op", Operations(MigrationContext.configure(connection))):
                migration.upgrade()
                self.assertIn("reference_name_audit_events", inspect(connection).get_table_names())
                columns = {column["name"] for column in inspect(connection).get_columns("reference_name_audit_events")}
                self.assertEqual(columns, {
                    "id", "reference_type", "reference_id", "actor_user_id",
                    "previous_name", "new_name", "created_at",
                })
                migration.downgrade()
            self.assertNotIn("reference_name_audit_events", inspect(connection).get_table_names())

    def test_populated_rename_history_blocks_downgrade(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        self.addCleanup(engine.dispose)
        migration = load_migration()
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE users (id UUID PRIMARY KEY)"))
            connection.execute(text("INSERT INTO users VALUES ('actor')"))
            with patch.object(migration, "op", Operations(MigrationContext.configure(connection))):
                migration.upgrade()
                connection.execute(text(
                    "INSERT INTO reference_name_audit_events "
                    "(id, reference_type, reference_id, actor_user_id, previous_name, new_name) "
                    "VALUES ('event', 'caliber', 'reference', 'actor', '223', '.223')"
                ))
                with self.assertRaisesRegex(RuntimeError, "rename audit history"):
                    migration.downgrade()
            self.assertEqual(connection.execute(text(
                "SELECT COUNT(*) FROM reference_name_audit_events"
            )).scalar_one(), 1)

    def test_postgres_ddl_contains_audit_constraints_and_actor_fk(self):
        output = io.StringIO()
        context = MigrationContext.configure(
            dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output},
        )
        migration = load_migration()
        with patch.object(migration, "op", Operations(context)):
            migration.upgrade()
        sql = output.getvalue()
        self.assertIn("CREATE TABLE reference_name_audit_events", sql)
        self.assertIn("reference_type IN ('manufacturer', 'caliber')", sql)
        self.assertIn("FOREIGN KEY(actor_user_id) REFERENCES users (id) ON DELETE RESTRICT", sql)
        self.assertIn("ix_reference_name_audit_reference_created", sql)


if __name__ == "__main__":
    unittest.main()
