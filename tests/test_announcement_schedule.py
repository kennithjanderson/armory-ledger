"""Deterministic timezone validation, real admin authorization and synthetic DB tests."""
import asyncio
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, literal
from sqlalchemy.pool import StaticPool

from app.schemas.announcement import AnnouncementRequest
from app.schemas.announcement_schedule import LocalSchedule, SchedulePreview
from app.models.announcement import Announcement
from app.services.announcement_service import active_announcements
import test_range_service as fixtures

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc


def local(value, zone="America/Chicago", occurrence=None):
    return dict(timezone=zone, local_time=value, occurrence=occurrence)


class ScheduleTests(unittest.TestCase):
    def test_utc_winter_summer_and_other_browser_zones(self):
        for zone, value, expected in [
            ("UTC", "2026-01-15T09:00", "2026-01-15T09:00:00+00:00"),
            ("America/Chicago", "2026-01-15T09:00", "2026-01-15T15:00:00+00:00"),
            ("America/Chicago", "2026-07-15T09:00", "2026-07-15T14:00:00+00:00"),
            ("Asia/Kolkata", "2026-07-15T09:00", "2026-07-15T03:30:00+00:00"),
        ]:
            self.assertEqual(LocalSchedule(**local(value, zone)).instant().isoformat(), expected)

    def test_gap_fold_and_invalid_zone(self):
        with self.assertRaisesRegex(ValueError, "does not exist"):
            LocalSchedule(**local("2026-03-08T02:30")).instant()
        with self.assertRaisesRegex(ValueError, "occurs twice"):
            LocalSchedule(**local("2026-11-01T01:30")).instant()
        for occurrence, hour in [("earlier", 6), ("later", 7)]:
            instant = LocalSchedule(**local("2026-11-01T01:30", occurrence=occurrence)).instant()
            self.assertEqual(instant, datetime(2026, 11, 1, hour, 30, tzinfo=UTC))
        for zone in ["Not/AZone", "/etc/passwd", "../UTC"]:
            with self.assertRaises(ValueError):
                LocalSchedule(**local("2026-01-15T09:00", zone))

    def test_existing_instants_survive_zone_changes_and_fold_with_microseconds(self):
        for original in ["2026-11-01T06:30:12.123456+00:00", "2026-11-01T07:30:12.123456+00:00"]:
            instant = original
            for zone in ["America/Chicago", "UTC", "Asia/Kolkata", "America/Chicago"]:
                preview = SchedulePreview(timezone=zone, instant=instant).preview()
                self.assertEqual(preview["utc"], original)
                choice = next(item["occurrence"] for item in preview["options"] if item["utc"] == original)
                instant = LocalSchedule(**local(preview["local_time"], zone, choice)).instant().isoformat()
                self.assertEqual(instant, original)

    def test_api_compatibility_and_server_revalidation(self):
        base = dict(title="Test", message="Message", starts_at=local("2026-07-15T09:00"), ends_at=local("2026-07-15T10:00"))
        request = AnnouncementRequest(**base)
        self.assertEqual(request.starts_at.hour, 14)
        self.assertEqual(set(request.model_dump()), {"title", "message", "severity", "enabled", "starts_at", "ends_at"})
        self.assertEqual(AnnouncementRequest(**{**base, "starts_at": "2026-07-15T09:00:00-05:00"}).starts_at, request.starts_at)
        for bad in ["2026-07-15T09:00", 123, local("2026-03-08T02:30"), local("2026-11-01T01:30"), {**local("2026-07-15T09:00"), "utc": "2026-07-15T00:00Z"}]:
            with self.assertRaises(ValueError):
                AnnouncementRequest(**{**base, "starts_at": bad})
        with self.assertRaises(ValueError):
            AnnouncementRequest(**{**base, "ends_at": base["starts_at"]})


class AnnouncementRouteTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.RangeServiceTests()
        self.f.make_engine = lambda: create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.session_user = {"id": str(self.f.owner.id), "is_admin": True}
        config = ModuleType("app.core.config")
        config.settings = SimpleNamespace(app_name="Test", app_version="test")
        session = ModuleType("app.db.session")
        session.SessionLocal = lambda: self.f.db
        rendering = ModuleType("app.main_templates")
        rendering.templates = SimpleNamespace()
        with patch.dict(sys.modules, {m.__name__: m for m in [config, session, rendering]}):
            spec = importlib.util.spec_from_file_location("app.core.dependencies", ROOT / "app/core/dependencies.py")
            deps = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(deps)
            with patch.dict(sys.modules, {"app.core.dependencies": deps}):
                spec = importlib.util.spec_from_file_location("schedule_admin_router", ROOT / "app/api/admin.py")
                admin = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(admin)
        self.app = FastAPI()
        def db():
            yield self.f.db
        self.app.dependency_overrides[deps.get_db] = db
        self.app.include_router(admin.router)
        @self.app.middleware("http")
        async def identity(request, call_next):
            request.scope["session"] = {"csrf_token": "test-token"}
            if self.session_user is not None:
                request.scope["session"]["user"] = self.session_user
            return await call_next(request)

    def request(self, path, payload, method="POST", csrf=True):
        async def run():
            async with AsyncClient(transport=ASGITransport(app=self.app), base_url="https://test.invalid") as client:
                return await client.request(method, path, json=payload, headers={"X-CSRF-Token": "test-token"} if csrf else {})
        return asyncio.run(run())

    def test_preview_create_edit_and_exact_preservation(self):
        path = "/admin/announcements/schedule-preview"
        self.assertEqual(self.request(path, local("2026-03-08T02:30")).status_code, 422)
        fold = self.request(path, local("2026-11-01T01:30"))
        self.assertEqual(len(fold.json()["options"]), 2)
        self.assertIsNone(fold.json()["utc"])
        payload = dict(title="Test", message="Hello", starts_at=local("2026-07-15T09:00:12.123456"), ends_at=local("2026-07-15T10:00:12.654321"))
        response = self.request("/admin/announcements", payload)
        self.assertEqual(response.status_code, 201, response.text)
        from uuid import UUID
        record = self.f.db.get(Announcement, UUID(response.json()["id"]))
        self.assertEqual(record.starts_at, datetime(2026, 7, 15, 14, 0, 12, 123456))
        original = record.starts_at
        converted = self.request(path, {"timezone": "America/Chicago", "instant": original.replace(tzinfo=UTC).isoformat()}).json()
        payload["starts_at"] = local(converted["local_time"])
        response = self.request(f"/admin/announcements/{record.id}", payload, "PUT")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(record.starts_at, original)
        payload["starts_at"] = local("2026-07-15T09:30")
        self.assertEqual(self.request(f"/admin/announcements/{record.id}", payload, "PUT").status_code, 200)
        self.assertEqual(record.starts_at.hour, 14)
        self.assertEqual(record.starts_at.minute, 30)
        payload["starts_at"] = local("2026-11-01T01:30")
        self.assertEqual(self.request(f"/admin/announcements/{record.id}", payload, "PUT").status_code, 422)

    def test_real_admin_dependency_and_csrf(self):
        for path in ["/admin/announcements", "/admin/announcements/schedule-preview"]:
            self.assertEqual(self.request(path, {}, csrf=False).status_code, 403)
            self.session_user["is_admin"] = False
            self.assertEqual(self.request(path, {}).status_code, 403)
            self.session_user = None
            self.assertEqual(self.request(path, {}).status_code, 401)
            self.session_user = {"id": str(self.f.owner.id), "is_admin": True}

    def test_visibility_start_inclusive_end_exclusive_disabled(self):
        start = datetime(2026, 7, 15, 14, tzinfo=UTC)
        end = datetime(2026, 7, 15, 15, tzinfo=UTC)
        self.f.db.add(Announcement(title="Visible", message="Test", severity="info", enabled=True,
                                  starts_at=start, ends_at=end, created_by_user_id=self.f.owner.id,
                                  updated_by_user_id=self.f.owner.id))
        self.f.db.add(Announcement(title="Disabled", message="Test", severity="info", enabled=False,
                                  starts_at=start, ends_at=end, created_by_user_id=self.f.owner.id,
                                  updated_by_user_id=self.f.owner.id))
        self.f.db.commit()
        for now, count in [(datetime(2026,7,15,13,59,59,tzinfo=UTC),0), (start,1), (end,0)]:
            with patch("app.services.announcement_service.func.now", return_value=literal(now)):
                self.assertEqual(len(active_announcements(self.f.db)), count)
        self.assertTrue(Announcement.__table__.c.starts_at.type.timezone)
        self.assertTrue(Announcement.__table__.c.ends_at.type.timezone)
