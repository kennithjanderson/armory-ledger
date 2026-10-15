"""Render real templates with synthetic data and check unchanged URL contracts."""
import ast
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace as Record
import unittest

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
from app.models.firearm import DatePrecision, FirearmStatus, FirearmType
from app.models.range_session import ShootingActivityType

ROOT = Path(__file__).resolve().parents[1]


class ShootingPageTests(unittest.TestCase):
    def setUp(self):
        self.env = Environment(loader=ChoiceLoader([
            DictLoader({"base.html": "{% block content %}{% endblock %}"}),
            FileSystemLoader(ROOT / "app/templates"),
        ]), autoescape=True)
        self.env.filters["format_number"] = str
        self.env.filters["format_money_amount"] = str
        self.firearm = Record(
            id="firearm", manufacturer=None, model="Test", status=FirearmStatus.OWNED,
            firearm_type=FirearmType.UNKNOWN, caliber=None, serial_number=None,
            manufacture_date_precision=DatePrecision.UNKNOWN,
            obtained_date_precision=DatePrecision.UNKNOWN, purchase_price=None,
            purchase_currency=None, notes=None, created_at=datetime(2026, 10, 1),
            updated_at=datetime(2026, 10, 1),
        )

    def test_firearm_history_labels_locations_rounds_and_links(self):
        history = [Record(
            session_id=str(index), activity_type=activity, location=None if index else "Gunport",
            occurred_date=date(2026, 10, 12), rounds_fired=index + 1,
        ) for index, activity in enumerate(ShootingActivityType)]
        html = self.env.get_template("firearms/detail.html").render(
            firearm=self.firearm, range_history=history, recorded_rounds=15,
        )
        self.assertIn("Shooting History", html)
        self.assertIn("Recorded Rounds Fired", html)
        self.assertIn("<strong>15</strong>", html)
        self.assertIn("Location unspecified", html)
        self.assertIn("Gunport", html)
        self.assertIn("2026-10-12", html)
        for index, activity in enumerate(ShootingActivityType):
            self.assertIn(activity.label, html)
            self.assertIn(f'href="/range/{index}"', html)
        self.assertEqual(html.count("View Activity →"), 5)

    def test_zero_total_and_empty_history(self):
        html = self.env.get_template("firearms/detail.html").render(
            firearm=self.firearm, range_history=[], recorded_rounds=0,
        )
        self.assertIn("<strong>0</strong>", html)
        self.assertIn("No shooting activities", html)

    def test_list_detail_and_navigation_use_existing_urls(self):
        session = Record(id="existing", activity_type=ShootingActivityType.DEFENSIVE,
                         occurred_date=date(2026, 10, 12), created_at=datetime(2026, 10, 12),
                         location=None, notes=None)
        listing = self.env.get_template("range/list.html").render(sessions=[session])
        detail = self.env.get_template("range/detail.html").render(
            range_session=session, firearm_records=[], total_rounds=0,
        )
        self.assertIn("Defensive Action", listing)
        self.assertIn('href="/range/existing"', listing)
        self.assertIn("Defensive Action", detail)
        self.assertIn('href="/range/existing/edit"', detail)
        self.assertEqual((ROOT / "app/templates/base.html").read_text().count(
            '<a href="/range">Shooting Log</a>'), 2)
        tree = ast.parse((ROOT / "app/api/range.py").read_text())
        routes = {(decorator.func.attr, ast.literal_eval(decorator.args[0]))
                  for function in tree.body if isinstance(function, ast.AsyncFunctionDef)
                  for decorator in function.decorator_list if isinstance(decorator, ast.Call)}
        self.assertTrue({("get", "/"), ("get", "/new"), ("get", "/{session_id}"),
                         ("get", "/{session_id}/edit"), ("post", "/"),
                         ("put", "/{session_id}")}.issubset(routes))
