"""Caliber alias service and admin-route tests using synthetic SQLite data."""
import asyncio
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

import test_range_service as fixtures
from app.models.audit_event import AuditEvent
from app.models.caliber import Caliber
from app.models.caliber_alias import CaliberAlias
from app.models.caliber_alias_audit_event import CaliberAliasAuditEvent
from app.models.reference_name_audit_event import ReferenceNameAuditEvent
from app.services.caliber_service import (
    add_caliber_alias,
    create_caliber,
    delete_caliber_alias,
    get_caliber_by_name_or_alias,
    list_selectable_calibers,
    rename_caliber,
)


ROOT = Path(__file__).resolve().parents[1]


class CaliberAliasServiceTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.RangeServiceTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.db = self.f.db

    def test_alias_resolves_only_to_explicit_canonical_caliber(self):
        alias = add_caliber_alias(
            self.db, self.f.nine.id, "  9 x 19  ", actor_user_id=self.f.owner.id,
        )
        self.assertEqual(alias.alias, "9 x 19")
        self.assertEqual(get_caliber_by_name_or_alias(self.db, " 9 X 19 ").id, self.f.nine.id)
        self.assertEqual(get_caliber_by_name_or_alias(self.db, "9mm Luger").id, self.f.nine.id)
        with self.assertRaisesRegex(ValueError, "already exists"):
            create_caliber(self.db, "9 X 19")
        self.assertEqual(self.f.nine.name, "9mm Luger")
        self.assertEqual(self.db.scalars(select(Caliber)).all(), [self.f.nine, self.f.rifle_caliber])

    def test_alias_add_remove_is_actor_audited_and_keeps_existing_ids(self):
        firearm_caliber_id = self.f.firearm.caliber_id
        product_caliber_id = self.f.lot.ammo_product.caliber_id
        alias = add_caliber_alias(
            self.db, self.f.nine.id, "9x19mm", actor_user_id=self.f.owner.id,
        )
        listed = list_selectable_calibers(self.db)
        nine = next(row for row in listed if row.id == self.f.nine.id)
        self.assertEqual([row.alias for row in nine.aliases], ["9x19mm"])
        delete_caliber_alias(
            self.db, caliber_id=self.f.nine.id, alias_id=alias.id,
            actor_user_id=self.f.owner.id,
        )
        self.assertIsNone(get_caliber_by_name_or_alias(self.db, "9x19mm"))
        self.assertEqual(self.f.firearm.caliber_id, firearm_caliber_id)
        self.assertEqual(self.f.lot.ammo_product.caliber_id, product_caliber_id)
        events = self.db.scalars(select(CaliberAliasAuditEvent)).all()
        self.assertEqual(len(events), 2)
        by_action = {event.action: event for event in events}
        self.assertEqual(by_action["created"].actor_user_id, self.f.owner.id)
        self.assertEqual((by_action["created"].previous_alias, by_action["created"].new_alias), (None, "9x19mm"))
        self.assertEqual((by_action["deleted"].previous_alias, by_action["deleted"].new_alias), ("9x19mm", None))
        self.assertEqual(self.db.scalars(select(AuditEvent)).all(), [])

    def test_alias_conflicts_with_canonical_names_or_existing_aliases(self):
        with self.assertRaisesRegex(ValueError, "already resolves to another caliber"):
            add_caliber_alias(
                self.db, self.f.nine.id, "5.56 NATO", actor_user_id=self.f.owner.id,
            )
        add_caliber_alias(self.db, self.f.nine.id, "9x19", actor_user_id=self.f.owner.id)
        with self.assertRaisesRegex(ValueError, "already resolves to"):
            add_caliber_alias(
                self.db, self.f.rifle_caliber.id, " 9X19 ", actor_user_id=self.f.owner.id,
            )
        with self.assertRaisesRegex(ValueError, "already resolves"):
            add_caliber_alias(
                self.db, self.f.nine.id, "9mm Luger", actor_user_id=self.f.owner.id,
            )
        self.assertEqual(self.db.query(CaliberAlias).count(), 1)
        self.assertEqual(self.db.query(CaliberAliasAuditEvent).count(), 1)

    def test_normalized_unique_index_guards_case_and_outer_whitespace(self):
        self.db.add(CaliberAlias(caliber_id=self.f.nine.id, alias="9 x 19"))
        self.db.commit()
        self.db.add(CaliberAlias(caliber_id=self.f.rifle_caliber.id, alias=" 9 X 19 "))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()
        self.assertEqual(self.db.query(CaliberAlias).count(), 1)

    def test_entry_forms_offer_alias_labels_with_the_canonical_id(self):
        add_caliber_alias(self.db, self.f.nine.id, "9x19", actor_user_id=self.f.owner.id)
        choices = list_selectable_calibers(self.db)
        nine = next(row for row in choices if row.id == self.f.nine.id)
        self.assertEqual(nine.aliases[0].caliber_id, self.f.nine.id)
        for name in (
            "firearms/new.html", "firearms/edit.html",
            "ammunition/new.html", "ammunition/edit.html",
        ):
            source = (ROOT / "app/templates" / name).read_text()
            self.assertIn("for alias in caliber.aliases", source)
            self.assertIn('value="{{ caliber.id }}">{{ alias.alias }} → {{ caliber.name }}', source)

    def test_rename_preserves_firearm_and_product_ids_and_old_name_alias(self):
        firearm_caliber_id = self.f.firearm.caliber_id
        product_caliber_id = self.f.lot.ammo_product.caliber_id
        renamed = rename_caliber(
            self.db, self.f.nine.id, "9 mm", actor_user_id=self.f.owner.id,
        )
        self.assertEqual(renamed.id, self.f.nine.id)
        self.assertEqual(renamed.name, "9 mm")
        self.assertEqual(self.f.firearm.caliber_id, firearm_caliber_id)
        self.assertEqual(self.f.lot.ammo_product.caliber_id, product_caliber_id)
        self.assertEqual(get_caliber_by_name_or_alias(self.db, "9 mm").id, self.f.nine.id)
        self.assertEqual(get_caliber_by_name_or_alias(self.db, "9mm Luger").id, self.f.nine.id)
        event = self.db.scalar(select(ReferenceNameAuditEvent))
        self.assertEqual((event.reference_type, event.reference_id, event.actor_user_id,
                          event.previous_name, event.new_name),
                         ("caliber", self.f.nine.id, self.f.owner.id, "9mm Luger", "9 mm"))
        self.assertEqual(self.db.query(CaliberAliasAuditEvent).count(), 1)

    def test_rename_promotes_own_alias_and_rejects_conflicts_atomically(self):
        alias = add_caliber_alias(
            self.db, self.f.nine.id, "9x19", actor_user_id=self.f.owner.id,
        )
        renamed = rename_caliber(
            self.db, self.f.nine.id, "9x19", actor_user_id=self.f.owner.id,
        )
        self.assertEqual(renamed.name, "9x19")
        aliases = self.db.scalars(select(CaliberAlias).where(
            CaliberAlias.caliber_id == self.f.nine.id
        )).all()
        self.assertEqual([row.alias for row in aliases], ["9mm Luger"])
        events = self.db.scalars(select(CaliberAliasAuditEvent)).all()
        self.assertEqual({(row.action, row.previous_alias, row.new_alias) for row in events}, {
            ("created", None, "9x19"),
            ("deleted", "9x19", None),
            ("created", None, "9mm Luger"),
        })
        self.assertIsNotNone(alias)
        with self.assertRaisesRegex(ValueError, "conflicts with another"):
            rename_caliber(
                self.db, self.f.nine.id, "5.56 NATO", actor_user_id=self.f.owner.id,
            )
        self.assertEqual(self.f.nine.name, "9x19")
        self.assertEqual(self.db.query(ReferenceNameAuditEvent).count(), 1)


class CaliberAliasRouteTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.RangeServiceTests()
        self.f.make_engine = lambda: create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.db = self.f.db
        self.f.owner.is_admin = True
        self.db.commit()
        self.session_user = {"id": str(self.f.owner.id), "is_admin": True}
        self.render_calls = []

        config = ModuleType("app.core.config")
        config.settings = SimpleNamespace(app_name="Test", app_version="test")
        dependencies = ModuleType("app.core.dependencies")
        dependencies.get_db = lambda: iter((self.db,))

        def require_admin(request: Request):
            if request.session.get("user", {}).get("is_admin") is not True:
                from fastapi import HTTPException
                raise HTTPException(status_code=403, detail="Armory Admin access required.")
            user_id = request.session["user"].get("id")
            return self.f.owner if user_id == str(self.f.owner.id) else self.f.other

        dependencies.require_admin = require_admin
        csrf = ModuleType("app.core.csrf")
        csrf.csrf_token = lambda _request: "test-token"

        def require_csrf(request: Request):
            if request.headers.get("X-CSRF-Token") != "test-token":
                from fastapi import HTTPException
                raise HTTPException(status_code=403, detail="Invalid CSRF token.")

        csrf.require_csrf = require_csrf
        rendering = ModuleType("app.main_templates")

        def template_response(**kwargs):
            self.render_calls.append(kwargs)
            return __import__("starlette.responses", fromlist=["JSONResponse"]).JSONResponse(
                {"template": kwargs["name"]}
            )

        rendering.templates = SimpleNamespace(TemplateResponse=template_response)
        with patch.dict(sys.modules, {
            "app.core.config": config,
            "app.core.dependencies": dependencies,
            "app.core.csrf": csrf,
            "app.main_templates": rendering,
        }):
            spec = importlib.util.spec_from_file_location("caliber_alias_admin", ROOT / "app/api/admin.py")
            self.admin = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.admin)

        self.app = FastAPI()

        def get_test_db():
            yield self.db

        self.app.dependency_overrides[self.admin.get_db] = get_test_db

        @self.app.middleware("http")
        async def identity(request, call_next):
            request.scope["session"] = {"csrf_token": "test-token"}
            if self.session_user is not None:
                request.scope["session"]["user"] = self.session_user
            return await call_next(request)

        self.app.include_router(self.admin.router)

    def request(self, method, path, payload=None, *, csrf=True):
        async def run():
            async with AsyncClient(transport=ASGITransport(app=self.app), base_url="https://test.invalid") as client:
                return await client.request(
                    method, path, json=payload,
                    headers={"X-CSRF-Token": "test-token"} if csrf else {},
                )
        return asyncio.run(run())

    def test_admin_page_and_mutations_require_armory_admin_and_csrf(self):
        path = f"/admin/calibers/{self.f.nine.id}/aliases"
        self.assertEqual(self.request("GET", path).status_code, 200)
        self.assertEqual(self.render_calls[-1]["name"], "admin/caliber_aliases.html")
        self.assertEqual(self.render_calls[-1]["context"]["caliber"].id, self.f.nine.id)
        self.assertEqual(self.request("POST", path, {"alias": "9x19"}, csrf=False).status_code, 403)

        self.session_user = {"id": str(self.f.other.id), "is_admin": False}
        self.assertEqual(self.request("GET", path).status_code, 403)
        self.assertEqual(self.request("POST", path, {"alias": "9x19"}).status_code, 403)
        self.assertEqual(self.db.query(CaliberAlias).count(), 0)

    def test_admin_can_add_and_remove_audited_alias_but_not_edit_it(self):
        path = f"/admin/calibers/{self.f.nine.id}/aliases"
        created = self.request("POST", path, {"alias": "9 x 19"})
        self.assertEqual(created.status_code, 201, created.text)
        alias_id = created.json()["id"]
        self.assertEqual(get_caliber_by_name_or_alias(self.db, "9 X 19").id, self.f.nine.id)
        self.assertEqual(self.request("PUT", f"{path}/{alias_id}", {"alias": "other"}).status_code, 405)
        removed = self.request("DELETE", f"{path}/{alias_id}")
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertEqual(self.db.query(CaliberAlias).count(), 0)
        self.assertEqual(self.db.query(CaliberAliasAuditEvent).count(), 2)

    def test_duplicate_alias_returns_conflict_without_extra_audit_event(self):
        path = f"/admin/calibers/{self.f.nine.id}/aliases"
        self.assertEqual(self.request("POST", path, {"alias": "9x19"}).status_code, 201)
        duplicate = self.request("POST", path, {"alias": " 9X19 "})
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(self.db.query(CaliberAlias).count(), 1)
        self.assertEqual(self.db.query(CaliberAliasAuditEvent).count(), 1)

    def test_canonical_rename_route_requires_admin_csrf_and_audits_change(self):
        path = f"/admin/calibers/{self.f.nine.id}/name"
        self.assertEqual(self.request("PUT", path, {"name": "9 mm"}, csrf=False).status_code, 403)
        self.session_user = {"id": str(self.f.other.id), "is_admin": False}
        self.assertEqual(self.request("PUT", path, {"name": "9 mm"}).status_code, 403)
        self.assertEqual(self.f.nine.name, "9mm Luger")

        self.session_user = {"id": str(self.f.owner.id), "is_admin": True}
        response = self.request("PUT", path, {"name": "9 mm"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["name"], "9 mm")
        self.assertEqual(self.db.query(ReferenceNameAuditEvent).count(), 1)


if __name__ == "__main__":
    unittest.main()
