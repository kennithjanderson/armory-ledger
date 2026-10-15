"""Synthetic Jinja form and stateless Python conversion bridge for DOM tests."""
from datetime import datetime
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if len(sys.argv) > 1 and sys.argv[1] == "preview":
    from app.schemas.announcement_schedule import SchedulePreview
    try:
        print(json.dumps({"ok": True, "data": SchedulePreview.model_validate_json(sys.argv[2]).preview()}))
    except ValueError as exc:
        print(json.dumps({"ok": False, "data": {"detail": str(exc)}}))
else:
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": "{% block content %}{% endblock %}", "partials/admin_navigation.html": ""}),
        FileSystemLoader(ROOT / "app/templates"),
    ]), autoescape=True)
    announcement = None
    if len(sys.argv) > 1:
        announcement = SimpleNamespace(id="test-id", title="Existing", message="Message", severity="info", enabled=True,
            starts_at=datetime.fromisoformat("2026-11-01T07:30:12.123456+00:00"),
            ends_at=datetime.fromisoformat("2026-11-01T08:30:12.654321+00:00"))
    print(env.get_template("admin/announcements/form.html").render(announcement=announcement,
        csrf_token="token", app_name="Test", app_version="test", url_for=lambda *a, **kw: "/static/" + kw["path"]))
