"""Render the real range form with synthetic, owner-scoped options for DOM tests."""
from pathlib import Path
from types import SimpleNamespace as Record

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]
env = Environment(
    loader=ChoiceLoader([
        DictLoader({"base.html": "{% block content %}{% endblock %}"}),
        FileSystemLoader(ROOT / "app/templates"),
    ]),
    autoescape=True,
)
env.filters["format_number"] = str
firearms = [
    Record(id=id_, caliber_id=caliber, model=id_, manufacturer=None)
    for id_, caliber in [("canik", "9mm"), ("rifle", "556"),
                         ("second9", "9mm"), ("unknown", None), ("empty", "45")]
]
lots = [
    Record(id=id_, is_merged=id_ == "merged9", lot_number="Batch <A>", ammo_product=Record(
        caliber_id=caliber, caliber=Record(name=caliber),
        brand=Record(name="Example"), grain_weight=124, projectile_type="FMJ",
    ))
    for id_, caliber in [("lot9", "9mm"), ("lot556", "556"), ("spent9", "9mm"), ("merged9", "9mm")]
]
print(env.get_template("range/new.html").render(
    activity_types=[Record(value=value, label=label) for value, label in [
        ("range", "Range Session"), ("hunting", "Hunting"), ("training", "Training"),
        ("defensive", "Defensive Action"), ("other", "Other"),
    ]],
    firearms=firearms, ammo_lots=lots,
    inventory_by_lot={"lot9": 100, "lot556": 80, "spent9": 0},
    edit_mode=False, initial_data=None, app_version="test",
    url_for=lambda *args, **kwargs: kwargs["path"],
))
