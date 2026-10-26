"""Manufacturer alias service and admin-route regression tests."""
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
from sqlalchemy.pool import StaticPool

import test_range_service as fixtures
from app.models.audit_event import AuditEvent
from app.models.manufacturer_alias_audit_event import ManufacturerAliasAuditEvent
from app.models.reference_name_audit_event import ReferenceNameAuditEvent
from app.models.organization import ManufacturerProfile, Organization
from app.models.organization_alias import OrganizationAlias
from app.models.accessory import Accessory
from app.models.ammo_brand import AmmoBrand
from app.services.manufacturer_service import (
    add_manufacturer_alias,
    create_manufacturer,
    delete_manufacturer_alias,
    find_exact_manufacturer,
    find_similar_manufacturers,
    rename_manufacturer,
)


ROOT = Path(__file__).resolve().parents[1]


class ManufacturerAliasServiceTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.RangeServiceTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.db = self.f.db
        self.manufacturer = Organization(id=uuid4(), name="Smith & Wesson")
        self.db.add(self.manufacturer)
        self.db.flush()
        self.db.add(ManufacturerProfile(organization_id=self.manufacturer.id, is_selectable=True))
        self.db.commit()

    def test_alias_resolves_to_canonical_and_blocks_duplicate_creation(self):
        alias = add_manufacturer_alias(
            self.db, self.manufacturer.id, "  S&W  ", actor_user_id=self.f.owner.id,
        )
        self.assertEqual(alias.alias, "S&W")
        self.assertEqual(find_exact_manufacturer(self.db, "s&w").id, self.manufacturer.id)
        self.assertEqual(find_exact_manufacturer(self.db, " smith   & wesson ").id, self.manufacturer.id)
        self.assertEqual(find_similar_manufacturers(self.db, "S&W")[0][0].id, self.manufacturer.id)
        with self.assertRaisesRegex(ValueError, "already exists as"):
            create_manufacturer(self.db, "S&W")
        self.assertEqual(self.db.scalars(select(Organization).where(Organization.name == "S&W")).all(), [])
        self.assertEqual(self.manufacturer.name, "Smith & Wesson")

    def test_alias_remove_and_readd_are_audited_and_leave_inventory_ids_unchanged(self):
        self.f.firearm.manufacturer_id = self.manufacturer.id
        self.db.commit()
        alias = add_manufacturer_alias(
            self.db, self.manufacturer.id, "S&W", actor_user_id=self.f.owner.id,
        )
        self.assertEqual(find_exact_manufacturer(self.db, "S&W").id, self.manufacturer.id)
        replacement = add_manufacturer_alias(
            self.db, self.manufacturer.id, "Smith and Wesson", actor_user_id=self.f.owner.id,
        )
        self.assertEqual(find_exact_manufacturer(self.db, "Smith and Wesson").id, self.manufacturer.id)
        delete_manufacturer_alias(
            self.db, organization_id=self.manufacturer.id, alias_id=alias.id,
            actor_user_id=self.f.owner.id,
        )
        delete_manufacturer_alias(
            self.db, organization_id=self.manufacturer.id, alias_id=replacement.id,
            actor_user_id=self.f.owner.id,
        )
        self.assertEqual(find_exact_manufacturer(self.db, "Smith and Wesson"), None)
        self.assertEqual(self.f.firearm.manufacturer_id, self.manufacturer.id)
        self.assertEqual(self.manufacturer.name, "Smith & Wesson")
        events = self.db.scalars(select(ManufacturerAliasAuditEvent)).all()
        by_alias_action = {(event.alias_id, event.action): event for event in events}
        self.assertEqual(len(events), 4)
        self.assertTrue(all(event.actor_user_id == self.f.owner.id for event in events))
        self.assertEqual((by_alias_action[(alias.id, "created")].previous_alias, by_alias_action[(alias.id, "created")].new_alias), (None, "S&W"))
        self.assertEqual((by_alias_action[(alias.id, "deleted")].previous_alias, by_alias_action[(alias.id, "deleted")].new_alias), ("S&W", None))
        self.assertEqual((by_alias_action[(replacement.id, "created")].previous_alias, by_alias_action[(replacement.id, "created")].new_alias), (None, "Smith and Wesson"))
        self.assertEqual((by_alias_action[(replacement.id, "deleted")].previous_alias, by_alias_action[(replacement.id, "deleted")].new_alias), ("Smith and Wesson", None))
        self.assertEqual(self.db.scalars(select(AuditEvent)).all(), [])

    def test_alias_conflicts_with_other_canonical_name_or_alias(self):
        other = Organization(id=uuid4(), name="S and W")
        self.db.add(other)
        self.db.flush()
        self.db.add(ManufacturerProfile(organization_id=other.id, is_selectable=True))
        self.db.commit()
        with self.assertRaisesRegex(ValueError, "already resolves to another manufacturer"):
            add_manufacturer_alias(self.db, self.manufacturer.id, "S and W", actor_user_id=self.f.owner.id)
        alias = add_manufacturer_alias(
            self.db, self.manufacturer.id, "S&W", actor_user_id=self.f.owner.id,
        )
        with self.assertRaisesRegex(ValueError, "already resolves to"):
            add_manufacturer_alias(self.db, other.id, " s&w ", actor_user_id=self.f.owner.id)
        self.assertEqual(alias.alias, "S&W")

    def test_rename_preserves_ids_adds_old_name_alias_and_records_actor(self):
        self.f.firearm.manufacturer_id = self.manufacturer.id
        brand = self.db.scalar(select(AmmoBrand))
        brand.manufacturer_id = self.manufacturer.id
        accessory = Accessory(
            id=uuid4(), owner_id=self.f.owner.id, manufacturer_id=self.manufacturer.id,
            name="Light", quantity=1,
        )
        self.db.add(accessory)
        self.db.commit()
        manufacturer_id = self.manufacturer.id
        firearm_id = self.f.firearm.manufacturer_id
        brand_id = brand.manufacturer_id
        accessory_id = accessory.manufacturer_id

        renamed = rename_manufacturer(
            self.db, manufacturer_id, "Smith and Wesson", actor_user_id=self.f.owner.id,
        )

        self.assertEqual(renamed.name, "Smith and Wesson")
        self.assertEqual(renamed.id, manufacturer_id)
        self.assertEqual((self.f.firearm.manufacturer_id, brand.manufacturer_id,
                          accessory.manufacturer_id),
                         (firearm_id, brand_id, accessory_id))
        self.assertEqual(find_exact_manufacturer(self.db, "Smith and Wesson").id, manufacturer_id)
        self.assertEqual(find_exact_manufacturer(self.db, "Smith & Wesson").id, manufacturer_id)
        event = self.db.scalar(select(ReferenceNameAuditEvent))
        self.assertEqual((event.reference_type, event.reference_id, event.actor_user_id,
                          event.previous_name, event.new_name),
                         ("manufacturer", manufacturer_id, self.f.owner.id,
                          "Smith & Wesson", "Smith and Wesson"))
        self.assertEqual(self.db.query(ManufacturerAliasAuditEvent).count(), 1)

    def test_rename_promotes_own_alias_and_rejects_conflicts_atomically(self):
        alias = add_manufacturer_alias(
            self.db, self.manufacturer.id, "S&W", actor_user_id=self.f.owner.id,
        )
        renamed = rename_manufacturer(
            self.db, self.manufacturer.id, "S&W", actor_user_id=self.f.owner.id,
        )
        self.assertEqual(renamed.name, "S&W")
        aliases = self.db.scalars(select(OrganizationAlias).where(
            OrganizationAlias.organization_id == self.manufacturer.id
        )).all()
        self.assertEqual([row.alias for row in aliases], ["Smith & Wesson"])
        alias_events = self.db.scalars(select(ManufacturerAliasAuditEvent).order_by(
            ManufacturerAliasAuditEvent.created_at, ManufacturerAliasAuditEvent.action
        )).all()
        self.assertEqual({(row.action, row.previous_alias, row.new_alias) for row in alias_events}, {
            ("created", None, "S&W"),
            ("deleted", "S&W", None),
            ("created", None, "Smith & Wesson"),
        })
        self.assertIsNotNone(alias)
        self.assertEqual(self.db.query(ReferenceNameAuditEvent).count(), 1)

        other = Organization(id=uuid4(), name="Other Maker")
        self.db.add(other)
        self.db.flush()
        self.db.add(ManufacturerProfile(organization_id=other.id, is_selectable=False))
        self.db.flush()
        self.db.add(OrganizationAlias(organization_id=other.id, alias="Taken Name"))
        self.db.commit()
        with self.assertRaisesRegex(ValueError, "conflicts with another"):
            rename_manufacturer(
                self.db, self.manufacturer.id, "Taken Name", actor_user_id=self.f.owner.id,
            )
        self.assertEqual(self.manufacturer.name, "S&W")
        self.assertEqual(self.db.query(ReferenceNameAuditEvent).count(), 1)


class ManufacturerAliasRouteTests(unittest.TestCase):
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
        self.manufacturer = Organization(id=uuid4(), name="Smith & Wesson")
        self.db.add(self.manufacturer)
        self.db.flush()
        self.db.add(ManufacturerProfile(organization_id=self.manufacturer.id, is_selectable=True))
        self.f.owner.is_admin = True
        self.db.commit()
        self.session_user = {"id": str(self.f.owner.id), "is_admin": True}

        config = ModuleType("app.core.config")
        config.settings = SimpleNamespace(app_name="Test", app_version="test")
        dependencies = ModuleType("app.core.dependencies")
        dependencies.get_db = lambda: iter((self.db,))
        def require_admin(request: Request):
            if request.session.get("user", {}).get("is_admin") is not True:
                from fastapi import HTTPException
                raise HTTPException(status_code=403, detail="Armory Admin access required.")
            return self.f.owner if request.session["user"].get("id") == str(self.f.owner.id) else self.f.other
        dependencies.require_admin = require_admin
        csrf = ModuleType("app.core.csrf")
        csrf.csrf_token = lambda _request: "test-token"
        def require_csrf(request: Request):
            if request.headers.get("X-CSRF-Token") != "test-token":
                from fastapi import HTTPException
                raise HTTPException(status_code=403, detail="Invalid CSRF token.")
        csrf.require_csrf = require_csrf
        rendering = ModuleType("app.main_templates")
        rendering.templates = SimpleNamespace(
            TemplateResponse=lambda **kwargs: __import__("starlette.responses", fromlist=["JSONResponse"]).JSONResponse(
                {"template": kwargs["name"]}
            )
        )
        with patch.dict(sys.modules, {
            "app.core.config": config,
            "app.core.dependencies": dependencies,
            "app.core.csrf": csrf,
            "app.main_templates": rendering,
        }):
            spec = importlib.util.spec_from_file_location("manufacturer_alias_admin", ROOT / "app/api/admin.py")
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

    def test_admin_only_routes_and_csrf_protect_alias_mutations(self):
        path = f"/admin/manufacturers/{self.manufacturer.id}/aliases"
        self.assertEqual(self.request("GET", path).status_code, 200)
        self.assertEqual(self.request("POST", path, {"alias": "S&W"}, csrf=False).status_code, 403)

        self.session_user = {"id": str(self.f.other.id), "is_admin": False}
        self.f.other.is_admin = False
        self.db.commit()
        self.assertEqual(self.request("GET", path).status_code, 403)
        self.assertEqual(self.request("POST", path, {"alias": "S&W"}).status_code, 403)
        self.assertEqual(self.db.scalars(select(OrganizationAlias)).all(), [])

    def test_admin_can_add_and_remove_alias_with_audit_but_cannot_edit(self):
        path = f"/admin/manufacturers/{self.manufacturer.id}/aliases"
        created = self.request("POST", path, {"alias": "S&W"})
        self.assertEqual(created.status_code, 201, created.text)
        alias_id = created.json()["id"]
        self.assertEqual(find_exact_manufacturer(self.db, "S&W").name, "Smith & Wesson")
        updated = self.request("PUT", f"{path}/{alias_id}", {"alias": "Smith and Wesson"})
        self.assertEqual(updated.status_code, 405)
        removed = self.request("DELETE", f"{path}/{alias_id}")
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertEqual(self.db.scalar(select(OrganizationAlias.id)), None)
        self.assertEqual(self.db.query(ManufacturerAliasAuditEvent).count(), 2)

    def test_canonical_rename_route_requires_admin_csrf_and_audits_change(self):
        path = f"/admin/manufacturers/{self.manufacturer.id}/name"
        self.assertEqual(self.request("PUT", path, {"name": "Smith and Wesson"}, csrf=False).status_code, 403)
        self.session_user = {"id": str(self.f.other.id), "is_admin": False}
        self.assertEqual(self.request("PUT", path, {"name": "Smith and Wesson"}).status_code, 403)
        self.assertEqual(self.manufacturer.name, "Smith & Wesson")

        self.session_user = {"id": str(self.f.owner.id), "is_admin": True}
        response = self.request("PUT", path, {"name": "Smith and Wesson"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["name"], "Smith and Wesson")
        self.assertEqual(self.db.query(ReferenceNameAuditEvent).count(), 1)

    def test_duplicate_conflict_returns_client_error_without_mutation(self):
        path = f"/admin/manufacturers/{self.manufacturer.id}/aliases"
        first = self.request("POST", path, {"alias": "S&W"})
        self.assertEqual(first.status_code, 201, first.text)
        duplicate = self.request("POST", path, {"alias": "  s&w  "})
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(self.db.query(OrganizationAlias).count(), 1)
        self.assertEqual(self.db.query(ManufacturerAliasAuditEvent).count(), 1)


if __name__ == "__main__":
    unittest.main()
