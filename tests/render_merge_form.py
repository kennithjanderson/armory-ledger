from datetime import datetime
from pathlib import Path
from types import SimpleNamespace as Record

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

env = Environment(loader=ChoiceLoader([
    DictLoader({"base.html": "{% block content %}{% endblock %}"}),
    FileSystemLoader(Path(__file__).resolve().parents[1] / "app/templates"),
]), autoescape=True)
env.filters["format_number"] = str
lot = Record(id="source", lot_number=None, created_at=datetime(2026, 10, 12), ammo_product=Record(
    brand=Record(name="Test"), caliber=Record(name="9mm"), grain_weight=124, projectile_type="FMJ",
))
print(env.get_template("ammunition/merge.html").render(
    lot=lot, source_quantity=200, csrf_token="test-token", app_version="test",
    candidates=[Record(id="destination", ammo_product=lot.ammo_product, created_at=datetime(2026, 10, 12)),
                Record(id="second", ammo_product=lot.ammo_product, created_at=datetime(2026, 10, 13))],
    balances={"destination": 200, "second": 50}, url_for=lambda *args, **kwargs: kwargs["path"],
))
