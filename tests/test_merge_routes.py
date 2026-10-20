"""Actual ASGI routers/templates with injected identity and an in-memory DB.

Does not import Settings, the production session factory, OIDC, or app.main.
"""
import asyncio
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.templating import Jinja2Templates
from httpx import ASGITransport, AsyncClient
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

import test_ammo_merging as fixtures
from app.models.ammo_inventory_transaction import AmmoInventoryTransaction, AmmoTransactionType
from app.models.ammo_lot import AmmoLot
from app.models.ammo_brand import AmmoBrand
from app.models.ammo_product import AmmoProduct
from app.models.organization import ManufacturerProfile, Organization
from app.models.organization_alias import OrganizationAlias
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]


class MergeRouteTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AmmoMergeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.db.add(ManufacturerProfile(
            organization_id=self.fixture.source.ammo_product.brand.manufacturer_id,
            is_selectable=True,
        ))
        self.fixture.db.add(OrganizationAlias(
            organization_id=self.fixture.source.ammo_product.brand.manufacturer_id,
            alias="Test Mfr",
        ))
        self.fixture.db.commit()
        self.authenticated = True
        self.current_user = self.fixture.f.owner
        async def get_user():
            if not self.authenticated:
                raise HTTPException(401)
            return self.current_user
        async def get_db():
            yield self.fixture.db
        env = Environment(loader=ChoiceLoader([
            DictLoader({"base.html": "{% block content %}{% endblock %}"}),
            FileSystemLoader(ROOT / "app/templates"),
        ]), autoescape=True)
        env.filters["format_number"] = str
        templates = Jinja2Templates(env=env)
        config, deps, rendering = [ModuleType(name) for name in (
            "app.core.config", "app.core.dependencies", "app.main_templates")]
        config.settings = SimpleNamespace(app_name="Test", app_version="test")
        deps.get_current_user, deps.get_db = get_user, get_db
        rendering.templates = templates
        self.app = FastAPI()
        @self.app.middleware("http")
        async def session_fixture(request, call_next):
            request.scope["session"] = {"user": {"is_admin": False}, "csrf_token": "test-token"}
            return await call_next(request)
        @self.app.get("/static/{path:path}", name="static")
        async def static(path):
            return {}
        with patch.dict(sys.modules, {m.__name__: m for m in [config, deps, rendering]}):
            for name in ["ammunition", "range"]:
                spec = importlib.util.spec_from_file_location(f"test_actual_{name}_router", ROOT / f"app/api/{name}.py")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                self.app.include_router(module.router)

    def request(self, method, url, **kwargs):
        async def run():
            async with AsyncClient(transport=ASGITransport(app=self.app), base_url="https://example.test") as client:
                return await client.request(method, url, **kwargs)
        return asyncio.run(run())

    def payload(self):
        return dict(destination_id=str(self.fixture.destination.id), expected_source=200,
                    expected_destination=200, confirmed=True)

    def test_confirmation_csrf_owner_and_success_history_views(self):
        source = str(self.fixture.source.id)
        destination = str(self.fixture.destination.id)
        self.assertIn("Merge Lot", self.request("GET", f"/ammunition/{source}").text)
        preview = self.request("GET", f"/ammunition/{source}/merge")
        self.assertEqual(preview.status_code, 200)
        self.assertIn(f'value="{destination}"', preview.text)
        self.assertNotIn(str(self.fixture.f.foreign_lot.id), preview.text)
        endpoint = f"/ammunition/{source}/merge"
        self.assertEqual(self.request("POST", endpoint, json=self.payload()).status_code, 403)
        headers = {"X-CSRF-Token": "test-token"}
        payload = self.payload()
        payload["confirmed"] = False
        self.assertEqual(self.request("POST", endpoint, json=payload, headers=headers).status_code, 422)
        response = self.request("POST", endpoint, json=self.payload(), headers=headers)
        self.assertEqual(response.status_code, 200)
        merge_id = response.json()["merge_id"]
        self.assertEqual(response.json()["redirect_url"], f"/ammunition/{destination}?merged={merge_id}")
        destination_page = self.request("GET", f"/ammunition/{destination}?merged={merge_id}").text
        self.assertIn("Merge completed", destination_page)
        self.assertIn("400", destination_page)
        self.assertIn("Merged from", destination_page)
        self.assertIn(f'class="record-back" href="/ammunition/{source}">View source lot →</a>', destination_page)
        self.assertEqual(destination_page.count("<h2>Merge History</h2>"), 1)
        source_page = self.request("GET", f"/ammunition/{source}").text
        self.assertIn("Merged — historical record", source_page)
        self.assertIn("Merged into", source_page)
        self.assertIn(f'class="record-back" href="/ammunition/{destination}">View destination lot →</a>', source_page)
        self.assertNotIn("Edit Ammunition", source_page)
        self.assertNotIn("Add Activity", source_page)
        self.assertIn(source, self.request("GET", "/ammunition/archive").text)
        self.assertNotIn(source, self.request("GET", f"/ammunition/calibers/{self.fixture.f.nine.id}").text)
        self.assertNotIn(f'value="{source}"', self.request("GET", "/range/new").text)
        self.assertEqual(self.request("POST", endpoint, json=self.payload(), headers=headers).status_code, 409)
        self.assertEqual(self.request("GET", f"/ammunition/{source}/edit").status_code, 409)

    def test_authentication_and_other_owner_cannot_access_merge_or_archive(self):
        endpoint = f"/ammunition/{self.fixture.source.id}/merge"
        self.authenticated = False
        self.assertEqual(self.request("GET", endpoint).status_code, 401)
        self.assertEqual(self.request("GET", "/ammunition/archive").status_code, 401)
        self.authenticated = True
        self.current_user = self.fixture.f.other
        self.assertEqual(self.request("GET", endpoint).status_code, 404)
        self.assertEqual(self.request("POST", endpoint, json=self.payload(),
                                      headers={"X-CSRF-Token": "test-token"}).status_code, 404)
        self.assertNotIn(str(self.fixture.source.id), self.request("GET", "/ammunition/archive").text)

    def test_lot_notification_settings_are_csrf_protected_and_owner_scoped(self):
        lot_id = self.fixture.source.id
        detail = self.request("GET", f"/ammunition/{lot_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn('id="ammunition-notification-settings"', detail.text)
        self.assertIn('data-csrf-token="test-token"', detail.text)

        endpoint = f"/ammunition/{lot_id}/notifications"
        settings = {
            "low_inventory_notifications_enabled": True,
            "low_inventory_threshold": 50,
            "depleted_notifications_enabled": True,
        }
        self.assertEqual(self.request("PUT", endpoint, json=settings).status_code, 403)
        headers = {"X-CSRF-Token": "test-token"}
        invalid = {**settings, "low_inventory_threshold": None}
        self.assertEqual(self.request("PUT", endpoint, json=invalid, headers=headers).status_code, 422)
        saved = self.request("PUT", endpoint, json=settings, headers=headers)
        self.assertEqual(saved.status_code, 200)
        self.assertTrue(self.fixture.source.low_inventory_notifications_enabled)
        self.assertEqual(self.fixture.source.low_inventory_threshold, 50)
        self.assertTrue(self.fixture.source.depleted_notifications_enabled)

        foreign = self.request("PUT", f"/ammunition/{self.fixture.f.foreign_lot.id}/notifications",
                               json=settings, headers=headers)
        self.assertEqual(foreign.status_code, 404)

    def test_record_link_visited_and_keyboard_focus_styles(self):
        import re
        css = (ROOT / "app/static/css/armory.css").read_text()
        rules = re.findall(r"([^{}]+)\{([^{}]+)\}", css)
        self.assertTrue(any(".record-back:visited" in selectors and "color: var(--navy-muted)" in body
                            for selectors, body in rules))
        self.assertTrue(any(".record-back:focus-visible" in selectors and "outline: 2px solid" in body
                            for selectors, body in rules))
        self.assertTrue(any(".record-back:hover" in selectors and "text-decoration: underline" in body
                            for selectors, body in rules))
        template = (ROOT / "app/templates/ammunition/detail.html").read_text()
        title = template.split("{% block title %}")[1].split("{% endblock %}")[0]
        self.assertNotIn("Merge History", title)

    def test_acquisition_suggestions_are_read_only_owner_scoped_and_explicit(self):
        payload = {
            "manufacturer_id": str(self.fixture.source.ammo_product.brand.manufacturer_id),
            "caliber_id": str(self.fixture.f.nine.id),
            "grain_weight": None,
            "projectile_type": None,
            "quantity": 25,
            "acquired_date": "2026-10-19",
        }
        before_lots = len(self.fixture.db.scalars(select(AmmoLot)).all())
        before_transactions = len(self.fixture.db.scalars(select(AmmoInventoryTransaction)).all())
        before_organizations = len(self.fixture.db.scalars(select(Organization)).all())
        result = self.request("POST", "/ammunition/", json=payload).json()
        self.assertFalse(result["success"])
        self.assertEqual(
            {item["id"] for item in result["duplicate_suggestions"]},
            {str(self.fixture.source.id), str(self.fixture.destination.id)},
        )
        self.assertTrue(all(item["quantity_on_hand"] > 0 for item in result["duplicate_suggestions"]))
        self.assertNotIn(str(self.fixture.f.foreign_lot.id), str(result))
        self.assertEqual(len(self.fixture.db.scalars(select(AmmoLot)).all()), before_lots)
        self.assertEqual(len(self.fixture.db.scalars(select(AmmoInventoryTransaction)).all()), before_transactions)

        # Acquisition requires an explicitly selected shared manufacturer.
        missing_selection = self.request("POST", "/ammunition/", json={
            **payload, "manufacturer_id": str(uuid4()), "create_separate_lot": True,
        }).json()
        self.assertFalse(missing_selection["success"])
        self.assertEqual(missing_selection["error"], "Selected manufacturer is invalid.")
        self.assertEqual(len(self.fixture.db.scalars(select(Organization)).all()), before_organizations)

        # Explicit New Lot and a supplied manufacturer lot number bypass suggestions.
        created = self.request("POST", "/ammunition/", json={
            **payload, "create_separate_lot": True,
        })
        self.assertTrue(created.json()["success"])
        with_number = self.request("POST", "/ammunition/", json={
            **payload, "lot_number": "maker-lot-9",
        })
        self.assertTrue(with_number.json()["success"])

    def test_activity_prefill_handoff_endpoint_remains_owner_scoped(self):
        initial = self.fixture.f.balance(self.fixture.source)
        self.assertEqual(
            self.request("GET", f"/ammunition/{self.fixture.source.id}/activity/new").status_code,
            200,
        )
        self.assertEqual(
            self.request("GET", f"/ammunition/{self.fixture.f.foreign_lot.id}/activity/new").status_code,
            404,
        )
        posted = self.request("POST", f"/ammunition/{self.fixture.source.id}/activity", json={
            "transaction_type": "acquired", "quantity": 25,
            "occurred_date": "2026-10-19", "notes": None,
        })
        self.assertEqual(posted.status_code, 200)
        self.assertTrue(posted.json()["success"])
        self.assertEqual(self.fixture.f.balance(self.fixture.source), initial + 25)

    def test_caliber_inventory_groups_active_and_depleted_lots_without_mutation(self):
        db = self.fixture.db
        owner_id = self.fixture.f.owner.id
        nine_id = self.fixture.f.nine.id
        depleted = AmmoLot(
            id=uuid4(), owner_id=owner_id,
            ammo_product_id=self.fixture.source.ammo_product_id,
        )
        alpha = Organization(id=uuid4(), name="Alpha Ordnance")
        alpha_brand = AmmoBrand(
            id=uuid4(), manufacturer=alpha, name="Alpha Target Loads",
        )
        alpha_product = AmmoProduct(
            id=uuid4(), brand=alpha_brand, caliber_id=nine_id,
            grain_weight=124, projectile_type="JHP",
        )
        alpha_lot = AmmoLot(
            id=uuid4(), owner_id=owner_id, ammo_product=alpha_product,
        )
        db.add_all([depleted, alpha, alpha_brand, alpha_product, alpha_lot])
        db.flush()
        db.add_all([
            AmmoInventoryTransaction(
                ammo_lot_id=depleted.id, transaction_type=AmmoTransactionType.ACQUIRED,
                quantity=10, occurred_at=datetime.now(timezone.utc),
            ),
            AmmoInventoryTransaction(
                ammo_lot_id=depleted.id, transaction_type=AmmoTransactionType.EXPENDED,
                quantity=10, occurred_at=datetime.now(timezone.utc),
            ),
            AmmoInventoryTransaction(
                ammo_lot_id=alpha_lot.id, transaction_type=AmmoTransactionType.ACQUIRED,
                quantity=50, occurred_at=datetime.now(timezone.utc),
            ),
        ])
        db.commit()
        original_balances = {
            lot.id: self.fixture.f.balance(lot)
            for lot in [self.fixture.source, self.fixture.destination, depleted, alpha_lot]
        }
        original_transaction_count = len(db.scalars(select(AmmoInventoryTransaction)).all())

        response = self.request("GET", f"/ammunition/calibers/{nine_id}")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("Active Inventory", html)
        self.assertIn("450", html)
        self.assertIn("4", html)
        self.assertIn('summary>Depleted Lots (1)</summary>', html)
        self.assertNotRegex(html, r'<details[^>]*\bopen(?:\s|>)')
        self.assertLess(
            html.index('class="ammunition-manufacturer-heading">Alpha Ordnance'),
            html.index('class="ammunition-manufacturer-heading">Test maker'),
        )
        self.assertIn(f'href="/ammunition/{depleted.id}"', html)
        self.assertEqual(
            {lot.id: self.fixture.f.balance(lot)
             for lot in [self.fixture.source, self.fixture.destination, depleted, alpha_lot]},
            original_balances,
        )
        self.assertEqual(len(db.scalars(select(AmmoInventoryTransaction)).all()), original_transaction_count)

        replenished = self.request("POST", f"/ammunition/{depleted.id}/activity", json={
            "transaction_type": "acquired", "quantity": 30,
            "occurred_date": "2026-10-19", "notes": None,
        })
        self.assertTrue(replenished.json()["success"])
        after = self.request("GET", f"/ammunition/calibers/{nine_id}").text
        self.assertIn("Depleted Lots (0)", after)
        self.assertEqual(self.fixture.f.balance(depleted), 30)
