"""Verify ammunition alert revision operations and safe downgrade ordering."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class AmmoNotificationMigrationTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / "migrations/versions/6ec8a2f145bd_ammunition_notifications.py"
        spec = importlib.util.spec_from_file_location("ammo_notification_migration", path)
        self.migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.migration)

    class RecordingOperations:
        def __init__(self):
            self.calls = []

        def add_column(self, *args): self.calls.append(("add_column", *args))
        def create_check_constraint(self, *args): self.calls.append(("create_check_constraint", *args))
        def drop_constraint(self, *args, **kwargs): self.calls.append(("drop_constraint", *args, kwargs))
        def drop_column(self, *args): self.calls.append(("drop_column", *args))

    def test_revision_follows_current_notification_preferences_revision(self):
        self.assertEqual(self.migration.revision, "6ec8a2f145bd")
        self.assertEqual(self.migration.down_revision, "a47c91e2d563")

    def test_upgrade_and_downgrade_include_defaults_checks_and_reverse_order(self):
        recorder = self.RecordingOperations()
        with patch.object(self.migration, "op", recorder):
            self.migration.upgrade()
        added = [call for call in recorder.calls if call[0] == "add_column"]
        self.assertEqual(
            [(call[1], call[2].name) for call in added],
            [("users", "ammo_notifications_in_app"), ("users", "ammo_notifications_email"),
             ("ammo_lots", "low_inventory_notifications_enabled"),
             ("ammo_lots", "low_inventory_threshold"),
             ("ammo_lots", "depleted_notifications_enabled")],
        )
        self.assertTrue(all(call[2].nullable is False and str(call[2].server_default.arg) == "false"
                            for call in added if call[2].name != "low_inventory_threshold"))
        checks = [call for call in recorder.calls if call[0] == "create_check_constraint"]
        self.assertEqual([call[1] for call in checks], [
            "ck_ammo_lots_low_inventory_threshold_positive",
            "ck_ammo_lots_low_inventory_enabled_has_threshold",
        ])
        recorder.calls.clear()
        with patch.object(self.migration, "op", recorder):
            self.migration.downgrade()
        dropped = [call for call in recorder.calls if call[0] == "drop_column"]
        self.assertEqual([call[2] for call in dropped], [
            "depleted_notifications_enabled", "low_inventory_threshold",
            "low_inventory_notifications_enabled", "ammo_notifications_email",
            "ammo_notifications_in_app",
        ])
        self.assertTrue(all(call[3]["type_"] == "check" for call in recorder.calls
                            if call[0] == "drop_constraint"))


if __name__ == "__main__":
    unittest.main()
