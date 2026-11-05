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

    def test_shared_inventory_lists_render_separate_collapsed_owner_groups(self):
        owner = Record(id="owner-1", display_name="Shared Owner")
        manufacturer = Record(name="Example Maker")
        caliber = Record(name="9mm")
        firearm = Record(
            id="firearm-1", model="Pistol", manufacturer=manufacturer,
            caliber=caliber, firearm_type=FirearmType.HANDGUN,
            status=FirearmStatus.OWNED, serial_number="LIST-PRIVATE-SERIAL",
            purchase_price="888.00", notes="LIST-PRIVATE-NOTE",
        )
        firearms_html = self.env.get_template("firearms/list.html").render(
            firearms=[], shared_firearm_groups=[{
                "owner": owner, "firearms": [firearm],
            }],
        )

        accessory = Record(
            id="accessory-1", name="Optic", model="A1", quantity=1,
            manufacturer=manufacturer, serial_number="LIST-PRIVATE-ACCESSORY",
            notes="LIST-PRIVATE-ACCESSORY-NOTE", storage_location="LIST-PRIVATE-LOCATION",
            firearm=Record(model="Pistol", manufacturer=manufacturer),
        )
        accessories_html = self.env.get_template("accessories/list.html").render(
            accessories=[], shared_accessory_groups=[{
                "owner": owner, "accessories": [accessory],
            }],
        )

        lot = Record(
            id="lot-1", lot_number="LOT-7",
            notes="LIST-PRIVATE-LOT-NOTE",
            ammo_product=Record(
                brand=Record(name="Brand", manufacturer=manufacturer),
                caliber=caliber, product_name="Practice", grain_weight=124,
                projectile_type="FMJ", notes="LIST-PRIVATE-PRODUCT-NOTE",
            ),
        )
        ammunition_html = self.env.get_template("ammunition/list.html").render(
            caliber_summaries=[], shared_ammunition_groups=[{
                "owner": owner, "lots": [lot], "inventory_by_lot": {"lot-1": 50},
            }],
        )

        session = Record(
            id="session-1", activity_type=ShootingActivityType.RANGE,
            occurred_date=date(2026, 11, 4),
        )
        range_html = self.env.get_template("range/list.html").render(
            sessions=[], shared_range_groups=[{
                "owner": owner,
                "sessions": [{"session": session, "total_rounds": 50}],
            }],
        )

        for html, label in (
            (firearms_html, "Firearms"),
            (accessories_html, "Accessories"),
            (ammunition_html, "Ammunition"),
            (range_html, "Shooting Log"),
        ):
            with self.subTest(section=label):
                self.assertIn("Shared with you", html)
                self.assertIn(f"Shared Owner’s {label}", html)
                self.assertIn("<details", html)
                self.assertNotIn("<details open", html)
        combined = firearms_html + accessories_html + ammunition_html + range_html
        for private_value in (
            "LIST-PRIVATE-SERIAL", "888.00", "LIST-PRIVATE-NOTE",
            "LIST-PRIVATE-ACCESSORY", "LIST-PRIVATE-ACCESSORY-NOTE",
            "LIST-PRIVATE-LOCATION", "LIST-PRIVATE-LOT-NOTE",
            "LIST-PRIVATE-PRODUCT-NOTE",
        ):
            self.assertNotIn(private_value, combined)

    def test_shared_detail_templates_omit_sensitive_fields(self):
        owner = Record(id="owner-1", display_name="Shared Owner")
        manufacturer = Record(name="Example Maker")
        firearm = Record(
            id="firearm-1", model="Pistol", manufacturer=manufacturer,
            caliber=Record(name="9mm"), firearm_type=FirearmType.HANDGUN,
            status=FirearmStatus.OWNED, serial_number="SECRET-FIREARM-SERIAL",
            purchase_price="999.99", notes="SECRET-FIREARM-NOTE",
        )
        firearm_html = self.env.get_template("shared/firearm_detail.html").render(
            firearm=firearm, owner=owner, recorded_rounds=None,
        )
        accessory = Record(
            name="Optic", model="A1", quantity=1, manufacturer=manufacturer,
            serial_number="SECRET-ACCESSORY-SERIAL", notes="SECRET-ACCESSORY-NOTE",
            purchase_location="SECRET-PURCHASE-LOCATION",
            storage_location="SECRET-STORAGE-LOCATION", firearm=None,
        )
        accessory_html = self.env.get_template("shared/accessory_detail.html").render(
            accessory=accessory, owner=owner,
        )
        product = Record(
            brand=Record(name="Brand", manufacturer=manufacturer),
            caliber=Record(name="9mm"), grain_weight=124,
            projectile_type="FMJ", product_name="Practice",
            manufacturer_sku="SKU-1", notes="SECRET-PRODUCT-NOTE",
        )
        lot = Record(id="lot-1", lot_number="LOT-7", notes="SECRET-LOT-NOTE",
                     ammo_product=product)
        ammo_html = self.env.get_template("shared/ammunition_detail.html").render(
            lot=lot, owner=owner, physical_on_hand=50,
        )
        session = Record(
            id="session-1", activity_type=ShootingActivityType.RANGE,
            occurred_date=date(2026, 11, 4), location="SECRET-LOCATION",
            notes="SECRET-SESSION-NOTE",
        )
        usage = Record(
            source_type=Record(value="other"), quantity=50,
            description="SECRET-AMMO-DESCRIPTION", ammo_lot=None,
        )
        range_html = self.env.get_template("shared/range_detail.html").render(
            session=session, owner=owner, total_rounds=50,
            firearm_records=[{
                "firearm": Record(id="firearm-1", model="Pistol", manufacturer=manufacturer),
                "rounds": 50, "ammo_usage": [usage],
            }],
        )

        rendered = firearm_html + accessory_html + ammo_html + range_html
        for secret in (
            "SECRET-FIREARM-SERIAL", "SECRET-FIREARM-NOTE", "SECRET-ACCESSORY-SERIAL",
            "SECRET-ACCESSORY-NOTE", "SECRET-PURCHASE-LOCATION", "SECRET-STORAGE-LOCATION",
            "SECRET-PRODUCT-NOTE", "SECRET-LOT-NOTE", "SECRET-LOCATION",
            "SECRET-SESSION-NOTE", "SECRET-AMMO-DESCRIPTION", "999.99",
        ):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, rendered)
