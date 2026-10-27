"""Inventory-sharing tests use only the existing synthetic in-memory SQLite fixture."""
import unittest
from pathlib import Path
import ast

from sqlalchemy import select

import test_range_service as fixtures
from app.models.inventory_share import InventoryShare, InventoryShareAuditEvent
from app.models.notification import NotificationEvent, NotificationRecipient, SystemSetting
from app.models.user import User
from app.services import notification_service, sharing_service


ROOT = Path(__file__).resolve().parents[1]
FULL = {"firearms": "rw", "ammunition": "rw", "accessories": "rw", "shooting_log": "rw"}
READ_ONLY = {"firearms": "ro", "ammunition": "none", "accessories": "none", "shooting_log": "ro"}


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
            self.db, owner_id=self.f.owner.id, actor_id=self.f.other.id, section="shooting_log"), "ro")
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

    def test_validation_and_mail_configuration_fail_closed(self):
        with self.assertRaises(ValueError):
            self.invite(permissions={**FULL, "firearms": "admin"})
        with self.assertRaises(ValueError):
            self.invite(permissions={key: "none" for key in FULL})
        self.db.get(SystemSetting, "email").value = {"enabled": False}
        self.db.commit()
        with self.assertRaises(sharing_service.InvitationEmailUnavailable):
            self.invite()
        self.assertEqual(self.db.scalars(select(InventoryShare)).all(), [])

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
