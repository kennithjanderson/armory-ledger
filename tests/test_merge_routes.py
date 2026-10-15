"""Actual ASGI routers/templates with injected identity and an in-memory DB.

Does not import Settings, the production session factory, OIDC, or app.main.
"""
import asyncio
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.templating import Jinja2Templates
from httpx import ASGITransport, AsyncClient
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

import test_ammo_merging as fixtures

ROOT = Path(__file__).resolve().parents[1]


class MergeRouteTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AmmoMergeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
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
