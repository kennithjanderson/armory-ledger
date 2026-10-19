from pathlib import Path
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

root = Path(__file__).resolve().parents[1]
environment = Environment(loader=ChoiceLoader([
    DictLoader({"base.html": "{% block content %}{% endblock %}"}),
    FileSystemLoader(root / "app/templates"),
]), autoescape=True)
print(environment.get_template("ammunition/new.html").render(
    app_name="Armory Ledger", app_version="test", current_user=None,
    is_admin=False, calibers=[], url_for=lambda *args, **kwargs: kwargs["path"],
))
