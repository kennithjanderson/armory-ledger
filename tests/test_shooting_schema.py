"""Migration and request validation checks without app settings or a live DB."""
import ast
import importlib.util
import io
from datetime import date
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.models.range_session import ShootingActivityType
from app.models.range_session_ammo_usage import RangeAmmoSourceType

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations/versions/82c1f947ad30_shooting_activity_type.py"


def revision_module():
    spec = importlib.util.spec_from_file_location("activity_revision", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ShootingSchemaTests(unittest.TestCase):
    def test_upgrade_backfills_and_enforces_values_downgrade_preserves_records(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        self.addCleanup(engine.dispose)
        revision = revision_module()
        self.assertEqual(revision.down_revision, "4d9a9a64bd4f")
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE range_sessions (id INTEGER PRIMARY KEY, location TEXT)"))
            connection.execute(text("INSERT INTO range_sessions VALUES (1, 'Existing location')"))
            operations = Operations(MigrationContext.configure(connection))
            with patch.object(revision, "op", operations):
                revision.upgrade()
                self.assertEqual(connection.execute(text(
                    "SELECT id, location, activity_type FROM range_sessions"
                )).one(), (1, "Existing location", "range"))
                for value in ["hunting", "training", "defensive", "other"]:
                    connection.execute(text("INSERT INTO range_sessions (activity_type) VALUES (:value)"), {"value": value})
                for value in ["invalid", None]:
                    with self.assertRaises(IntegrityError):
                        connection.execute(text("INSERT INTO range_sessions (activity_type) VALUES (:value)"), {"value": value})
                revision.downgrade()
                self.assertEqual(connection.execute(text("SELECT COUNT(*) FROM range_sessions")).scalar(), 5)
                self.assertEqual(connection.execute(text("SELECT location FROM range_sessions WHERE id=1")).scalar(), "Existing location")

    def test_postgres_migration_sql_and_linear_parent(self):
        revision = revision_module()
        output = io.StringIO()
        context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
        with patch.object(revision, "op", Operations(context)):
            revision.upgrade()
            revision.downgrade()
        sql = output.getvalue()
        self.assertIn("DEFAULT 'range' NOT NULL", sql)
        self.assertIn("ADD CONSTRAINT ck_range_sessions_activity_type CHECK", sql)
        self.assertIn("DROP CONSTRAINT ck_range_sessions_activity_type", sql)
        self.assertNotIn("DROP TABLE", sql)
        revisions = []
        for path in (ROOT / "migrations/versions").glob("*.py"):
            tree = ast.parse(path.read_text())
            for node in tree.body:
                if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) == "revision":
                    revisions.append(ast.literal_eval(node.value))
        self.assertEqual(revisions.count(revision.revision), 1)

    def test_actual_request_models_validate_activity_and_keep_old_payloads(self):
        # Execute only the actual schema declarations, avoiding router imports
        # that initialize Settings/database connections. No duplicate test schema.
        tree = ast.parse((ROOT / "app/api/range.py").read_text())
        classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
        namespace = dict(BaseModel=BaseModel, Field=Field, UUID=UUID, date=date,
                         RangeAmmoSourceType=RangeAmmoSourceType,
                         ShootingActivityType=ShootingActivityType)
        exec(compile(ast.Module(body=classes, type_ignores=[]), "range_request_models", "exec"), namespace)
        request = namespace["RangeSessionCreateRequest"]
        payload = {"occurred_date": "2026-10-12", "firearms": [{
            "firearm_id": str(uuid4()), "ammo_usage": [{"source_type": "other", "quantity": 3}],
        }]}
        self.assertEqual(request(**payload).activity_type, ShootingActivityType.RANGE)
        for value in ShootingActivityType:
            self.assertEqual(request(**payload, activity_type=value.value).activity_type, value)
        for value in ["invalid", None, "Hunting"]:
            with self.assertRaises(ValidationError):
                request(**payload, activity_type=value)
