"""Inventory-sharing tests use only the existing synthetic in-memory SQLite fixture."""
import unittest
from pathlib import Path
import ast
from decimal import Decimal

from sqlalchemy import select

import test_range_service as fixtures
from app.models.inventory_share import InventoryShare, InventoryShareAuditEvent
from app.models.notification import NotificationEvent, NotificationRecipient, SystemSetting
from app.models.user import User
from app.models.accessory import Accessory
from app.services import notification_service, sharing_service
from app.services.shared_inventory_service import (
    accessible_shares,
    accessory_read_view,
    ammunition_read_view,
    firearm_read_view,
    require_shared_read,
    shared_range_session_view,
)


ROOT = Path(__file__).resolve().parents[1]
FULL = {"firearms": "rw", "ammunition": "rw", "accessories": "rw", "shooting_log": "rw"}
READ_ONLY = {"firearms": "ro", "ammunition": "none", "accessories": "none", "shooting_log": "none"}
SHARED_READ_ONLY = {"firearms": "ro", "ammunition": "ro", "accessories": "ro", "shooting_log": "ro"}


class InventorySharingServiceTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.RangeServiceTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.db = self.f.db
        self.db.add(SystemSetting(key="email", value={"enabled": True}))
        self.db.commit()

    def invite(self, owner=None, email=None, permissions=None):
        return sharing_service.invite(
            self.db, owner=owner or self.f.owner,
            email=email or self.f.other.email, permissions=permissions or FULL,
        )

    def test_acceptance_is_explicit_directional_and_section_scoped(self):
        share = self.invite(permissions=READ_ONLY)
        self.assertEqual(share.status, "pending")
        self.assertEqual(share.recipient_id, self.f.other.id)
        self.assertEqual(sharing_service.section_access(
            self.db, owner_id=self.f.owner.id, actor_id=self.f.other.id, section="firearms"), "none")
        with self.assertRaises(PermissionError):
            sharing_service.require_section_access(
                self.db, owner_id=self.f.owner.id, actor_id=self.f.other.id,
                section="firearms", write=False,
            )

        sharing_service.respond(self.db, recipient=self.f.other, share_id=share.id, accept=True)
        self.assertEqual(sharing_service.section_access(
            self.db, owner_id=self.f.owner.id, actor_id=self.f.other.id, section="firearms"), "ro")
        self.assertEqual(sharing_service.section_access(
            self.db, owner_id=self.f.owner.id, actor_id=self.f.other.id, section="shooting_log"), "none")
        self.assertEqual(sharing_service.section_access(
            self.db, owner_id=self.f.owner.id, actor_id=self.f.other.id, section="ammunition"), "none")
        with self.assertRaises(PermissionError):
            sharing_service.require_section_access(
                self.db, owner_id=self.f.owner.id, actor_id=self.f.other.id,
                section="firearms", write=True,
            )

        # A's grant never creates access in the reverse direction.
        self.assertEqual(sharing_service.section_access(
            self.db, owner_id=self.f.other.id, actor_id=self.f.owner.id, section="firearms"), "none")
        self.f.other.is_admin = True
        self.db.commit()
        self.assertEqual(sharing_service.section_access(
            self.db, owner_id=self.f.owner.id, actor_id=self.f.other.id, section="ammunition"), "none")
        events = self.db.scalars(select(InventoryShareAuditEvent)).all()
        self.assertEqual([event.action for event in events], ["invited", "accepted"])

    def test_dependent_section_permissions_are_validated_and_effective(self):
        invalid = (
            {**FULL, "firearms": "none", "accessories": "ro"},
            {**FULL, "ammunition": "none", "shooting_log": "ro"},
            {**FULL, "firearms": "ro", "shooting_log": "rw"},
            {**FULL, "ammunition": "ro", "shooting_log": "rw"},
        )
        for permissions in invalid:
            with self.subTest(permissions=permissions), self.assertRaises(ValueError):
                sharing_service.normalize_permissions(permissions)

        read_only = {**FULL, "firearms": "ro", "ammunition": "ro",
                     "accessories": "rw", "shooting_log": "ro"}
        self.assertEqual(sharing_service.normalize_permissions(read_only)["shooting_log_access"], "ro")

        share = self.invite()
        sharing_service.respond(self.db, recipient=self.f.other, share_id=share.id, accept=True)
        share.firearms_access = "ro"
        share.shooting_log_access = "rw"  # Legacy or out-of-band invalid grant.
        self.db.commit()
        self.assertEqual(sharing_service.section_access(
            self.db, owner_id=self.f.owner.id, actor_id=self.f.other.id,
            section="shooting_log"), "ro")
        share.firearms_access = "none"
        self.db.commit()
        self.assertEqual(sharing_service.section_access(
            self.db, owner_id=self.f.owner.id, actor_id=self.f.other.id,
            section="shooting_log"), "none")
        self.assertEqual(sharing_service.section_access(
            self.db, owner_id=self.f.owner.id, actor_id=self.f.other.id,
            section="accessories"), "none")

    def test_read_views_are_allowlisted_and_live_grants_are_required(self):
        share = self.invite(permissions=SHARED_READ_ONLY)
        sharing_service.respond(self.db, recipient=self.f.other, share_id=share.id, accept=True)
        self.assertEqual(
            [owner.id for owner, _ in accessible_shares(
                self.db, recipient_id=self.f.other.id, section="firearms"
            )],
            [self.f.owner.id],
        )
        self.assertEqual(
            [owner.id for owner, _ in accessible_shares(
                self.db, recipient_id=self.f.other.id, section="shooting_log"
            )],
            [self.f.owner.id],
        )
        self.assertEqual(
            [owner.id for owner, _ in accessible_shares(
                self.db, recipient_id=self.f.other.id, section="accessories"
            )],
            [self.f.owner.id],
        )

        self.f.firearm.serial_number = "PRIVATE-SERIAL"
        self.f.firearm.purchase_price = Decimal("1234.56")
        self.f.firearm.purchase_currency = "USD"
        self.f.firearm.notes = "Private firearm notes"
        firearm_view = firearm_read_view(self.f.firearm)
        for private_field in ("serial_number", "purchase_price", "purchase_currency", "notes"):
            self.assertFalse(hasattr(firearm_view, private_field))
        self.assertEqual(firearm_view.model, "Canik")

        product = self.f.lot.ammo_product
        product.manufacturer_sku = "SKU-123"
        product.notes = "Private product note"
        self.f.lot.notes = "Private lot note"
        ammo_view = ammunition_read_view(self.f.lot)
        self.assertEqual(ammo_view.ammo_product.manufacturer_sku, "SKU-123")
        self.assertFalse(hasattr(ammo_view, "notes"))
        self.assertFalse(hasattr(ammo_view.ammo_product, "notes"))

        accessory = Accessory(
            owner_id=self.f.owner.id, name="Optic", model="A1", quantity=1,
            serial_number="PRIVATE-ACCESSORY-SERIAL", notes="Private accessory note",
            storage_location="Private storage", firearm_id=self.f.firearm.id,
        )
        self.db.add(accessory)
        self.db.flush()
        accessory_view = accessory_read_view(accessory, owner_id=self.f.owner.id)
        self.assertEqual(accessory_view.firearm.model, "Canik")
        for private_field in ("serial_number", "notes", "storage_location", "purchase_location"):
            self.assertFalse(hasattr(accessory_view, private_field))

        session = self.f.create()
        session.location = "Private range"
        session.notes = "Private session notes"
        self.db.commit()
        self.db.flush()
        range_view = shared_range_session_view(
            self.db, owner_id=self.f.owner.id, session_id=session.id,
        )
        self.assertIsNotNone(range_view)
        for private_field in ("location", "notes"):
            self.assertFalse(hasattr(range_view["session"], private_field))
        record = range_view["firearm_records"][0]
        self.assertEqual(record["firearm"].model, "Canik")
        self.assertFalse(hasattr(record["firearm"], "serial_number"))
        self.assertFalse(hasattr(record["ammo_usage"][0], "description"))

        self.f.other.is_admin = True
        self.db.commit()
        self.assertEqual(
            require_shared_read(
                self.db, owner_id=self.f.owner.id, actor_id=self.f.other.id,
                section="firearms",
            ).id,
            self.f.owner.id,
        )
        sharing_service.revoke(self.db, owner_id=self.f.owner.id, share_id=share.id)
        with self.assertRaises(LookupError):
            require_shared_read(
                self.db, owner_id=self.f.owner.id, actor_id=self.f.other.id,
                section="firearms",
            )

    def test_shared_range_view_rejects_cross_owner_firearm_reference(self):
        from datetime import date
        from app.models.range_session import RangeSession
        from app.models.range_session_firearm import RangeSessionFirearm

        session = RangeSession(
            owner_id=self.f.owner.id, occurred_date=date(2026, 10, 1),
            location="Do not expose", notes="Do not expose",
        )
        self.db.add(session)
        self.db.flush()
        self.db.add(RangeSessionFirearm(
            range_session_id=session.id, firearm_id=self.f.foreign_firearm.id,
            notes="Cross-owner relation",
        ))
        self.db.commit()
        self.assertIsNone(shared_range_session_view(
            self.db, owner_id=self.f.owner.id, session_id=session.id,
        ))

    def test_shared_templates_only_reference_approved_fields(self):
        expectations = {
            "shared/firearm_detail.html": (
                "firearm.serial_number", "firearm.purchase_price", "firearm.notes",
            ),
            "shared/accessory_detail.html": (
                "accessory.serial_number", "accessory.notes", "purchase_location",
                "storage_location",
            ),
            "shared/ammunition_detail.html": (
                "lot.notes", "product.notes", "transactions",
            ),
            "shared/range_detail.html": (
                "session.location", "session.notes", "usage.description",
                "session_firearm.notes",
            ),
        }
        for template, forbidden in expectations.items():
            source = (ROOT / "app/templates" / template).read_text()
            with self.subTest(template=template):
                for field in forbidden:
                    self.assertNotIn(field, source)

    def test_shared_detail_handlers_authenticate_and_recheck_grants(self):
        handlers = {
            "app/api/firearms.py": "shared_firearm_detail",
            "app/api/ammunition.py": "shared_ammunition_detail",
            "app/api/accessories.py": "shared_accessory_detail",
            "app/api/range.py": "shared_range_detail",
        }
        for relative_path, handler_name in handlers.items():
            tree = ast.parse((ROOT / relative_path).read_text())
            handler = next(
                node for node in tree.body
                if isinstance(node, ast.AsyncFunctionDef) and node.name == handler_name
            )
            with self.subTest(handler=handler_name):
                self.assertIn("Depends(get_current_user)", ast.unparse(handler.args))
                calls = {
                    node.func.id for node in ast.walk(handler)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                }
                self.assertIn("require_shared_read", calls)

        list_handlers = {
            "app/api/firearms.py": "firearm_list",
            "app/api/ammunition.py": "ammunition_list",
            "app/api/accessories.py": "accessory_list",
            "app/api/range.py": "range_list",
        }
        for relative_path, handler_name in list_handlers.items():
            tree = ast.parse((ROOT / relative_path).read_text())
            handler = next(
                node for node in tree.body
                if isinstance(node, ast.AsyncFunctionDef) and node.name == handler_name
            )
            calls = {
                node.func.id for node in ast.walk(handler)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            }
            with self.subTest(list_handler=handler_name):
                self.assertIn("accessible_shares", calls)

    def test_unregistered_email_is_queued_and_claimed_only_by_matching_account(self):
        share = self.invite(email="future.user@example.test", permissions=READ_ONLY)
        self.assertIsNone(share.recipient_id)
        event = self.db.scalar(select(NotificationEvent).where(
            NotificationEvent.event_key == f"share-invite:{share.id}"
        ))
        delivery = self.db.scalar(select(NotificationRecipient).where(
            NotificationRecipient.event_id == event.id
        ))
        self.assertEqual(delivery.user_id, self.f.owner.id)
        self.assertFalse(delivery.in_app)
        self.assertEqual(delivery.email_override, "future.user@example.test")
        self.assertNotIn("firearm", event.message.lower())
        message = notification_service.message_for(
            event, delivery, self.f.owner,
            {**notification_service.DEFAULT_MAIL, "from_address": "ledger@example.test",
             "base_url": "https://ledger.example.test"},
        )
        self.assertEqual(message["To"], "future.user@example.test")
        self.assertNotIn("Private", message.get_body(preferencelist=("plain",)).get_content())
        self.assertTrue(notification_service.share_invitation_delivery_valid(
            self.db, event, delivery, self.f.owner,
        ))
        delivery.email_override = "wrong@example.test"
        self.assertFalse(notification_service.share_invitation_delivery_valid(
            self.db, event, delivery, self.f.owner,
        ))
        delivery.email_override = "future.user@example.test"
        share.status = "revoked"
        self.assertFalse(notification_service.share_invitation_delivery_valid(
            self.db, event, delivery, self.f.owner,
        ))
        share.status = "pending"

        impostor = User(id=__import__("uuid").uuid4(), oidc_subject="impostor",
                        email="elsewhere@example.test", display_name="Impostor")
        self.db.add(impostor)
        self.db.commit()
        with self.assertRaises(LookupError):
            sharing_service.respond(self.db, recipient=impostor, share_id=share.id, accept=True)

        recipient = User(id=__import__("uuid").uuid4(), oidc_subject="future",
                         email="Future.User@example.test", display_name="Future User")
        self.db.add(recipient)
        self.db.commit()
        self.assertEqual(sharing_service.claim_pending_invitations(self.db, recipient), 1)
        self.assertEqual(share.recipient_id, recipient.id)
        self.assertEqual(delivery.user_id, recipient.id)
        self.assertTrue(delivery.in_app)
        self.assertEqual(sharing_service.section_access(
            self.db, owner_id=self.f.owner.id, actor_id=recipient.id, section="firearms"), "none")
        sharing_service.respond(self.db, recipient=recipient, share_id=share.id, accept=True)
        self.assertEqual(sharing_service.section_access(
            self.db, owner_id=self.f.owner.id, actor_id=recipient.id, section="firearms"), "ro")
        self.assertEqual([row.action for row in self.db.scalars(
            select(InventoryShareAuditEvent).order_by(InventoryShareAuditEvent.created_at)
        ).all()], ["invited", "claimed", "accepted"])

    def test_owner_can_change_grants_revoke_and_reinvite(self):
        share = self.invite(permissions=READ_ONLY)
        sharing_service.respond(self.db, recipient=self.f.other, share_id=share.id, accept=True)
        sharing_service.set_permissions(
            self.db, owner_id=self.f.owner.id, share_id=share.id, permissions=FULL,
        )
        self.assertEqual(sharing_service.section_access(
            self.db, owner_id=self.f.owner.id, actor_id=self.f.other.id, section="ammunition"), "rw")
        sharing_service.revoke(self.db, owner_id=self.f.owner.id, share_id=share.id)
        self.assertEqual(sharing_service.section_access(
            self.db, owner_id=self.f.owner.id, actor_id=self.f.other.id, section="firearms"), "none")
        self.assertEqual(share.status, "revoked")
        reinvited = self.invite(permissions=READ_ONLY)
        self.assertEqual(reinvited.id, share.id)
        self.assertEqual(reinvited.status, "pending")
        self.assertEqual([row.action for row in self.db.scalars(
            select(InventoryShareAuditEvent).order_by(InventoryShareAuditEvent.created_at)
        ).all()], ["invited", "accepted", "permissions_changed", "revoked", "reinvited"])

    def test_validation_and_email_disabled_existing_user_gets_in_app_invite(self):
        with self.assertRaises(ValueError):
            self.invite(permissions={**FULL, "firearms": "admin"})
        with self.assertRaises(ValueError):
            self.invite(permissions={key: "none" for key in FULL})
        self.db.get(SystemSetting, "email").value = {"enabled": False}
        self.db.commit()

        share = self.invite()
        event = self.db.scalar(select(NotificationEvent).where(
            NotificationEvent.event_key == f"share-invite:{share.id}"
        ))
        delivery = self.db.scalar(select(NotificationRecipient).where(
            NotificationRecipient.event_id == event.id
        ))
        self.assertEqual(delivery.user_id, self.f.other.id)
        self.assertTrue(delivery.in_app)
        self.assertEqual(delivery.email_state, "disabled")
        self.assertEqual(delivery.diagnostic, "Email disabled; in-app invitation delivered")

        with self.assertRaises(sharing_service.InvitationEmailUnavailable):
            self.invite(email="future.user@example.test")
        self.assertEqual(self.db.scalars(select(InventoryShare)).all(), [share])

    def test_migration_is_chained_and_downgrade_protects_live_shares(self):
        path = ROOT / "migrations/versions/12ef7a4b9c31_inventory_shares.py"
        tree = ast.parse(path.read_text())
        assignments = {
            node.targets[0].id: ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in {"revision", "down_revision"}
        }
        self.assertEqual(assignments, {"revision": "12ef7a4b9c31", "down_revision": "480378f66895"})
        source = path.read_text()
        for table, check in (
            ("inventory_shares", "ck_inventory_shares_has_access"),
            ("inventory_share_audit_events", "ck_inventory_share_audit_action"),
        ):
            self.assertIn(f'"{table}"', source)
            self.assertIn(check, source)
        self.assertIn('"email_override"', source)
        self.assertIn("Cannot downgrade inventory sharing", source)

    def test_router_authentication_and_mutation_csrf_are_declared_server_side(self):
        tree = ast.parse((ROOT / "app/api/sharing.py").read_text())
        router_call = next(
            node.value for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "router" for target in node.targets)
        )
        router_source = ast.unparse(router_call)
        self.assertIn("Depends(get_current_user)", router_source)
        mutating = {"create_invitation", "update_permissions", "revoke_invitation",
                    "accept_invitation", "decline_invitation"}
        seen = set()
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef) or node.name not in mutating:
                continue
            seen.add(node.name)
            decorators = " ".join(ast.unparse(decorator) for decorator in node.decorator_list)
            self.assertIn("Depends(require_csrf)", decorators, node.name)
        self.assertEqual(seen, mutating)


if __name__ == "__main__":
    unittest.main()
