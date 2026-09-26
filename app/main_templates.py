from decimal import Decimal, InvalidOperation
from datetime import timezone
from uuid import UUID

from fastapi.templating import Jinja2Templates

from app.db.session import SessionLocal
from app.models.user import User
from app.services.announcement_service import active_announcements


def announcement_context(request):
    """Provide public announcement content on every authenticated HTML page."""
    session_user = request.session.get("user")
    if not session_user:
        return {"active_announcements": []}
    try:
        user_id = UUID(session_user.get("id", ""))
    except (ValueError, TypeError, AttributeError):
        return {"active_announcements": []}
    with SessionLocal() as db:
        if db.get(User, user_id) is None:
            return {"active_announcements": []}
        # Do not expose management metadata to ordinary users.
        announcements = [
            {"title": item.title, "message": item.message, "severity": item.severity}
            for item in active_announcements(db)
        ]
    return {"active_announcements": announcements}


templates = Jinja2Templates(
    directory="app/templates", context_processors=[announcement_context],
)


def format_number(value):
    if value is None:
        return ""

    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return value

    if number == number.to_integral():
        return str(number.quantize(Decimal("1")))

    return format(number.normalize(), "f")


templates.env.filters["format_number"] = format_number


def format_decimal_input(value):
    """Return plain decimal text suitable for a numeric input."""
    if value is None:
        return ""
    return format(Decimal(str(value)), ".2f")


def format_money_amount(value, currency=None):
    """Format an amount for display without converting its currency."""
    if value is None:
        return ""
    amount = format(Decimal(str(value)), ",.2f")
    return f"${amount}" if currency == "USD" else amount


templates.env.filters["format_decimal_input"] = format_decimal_input
templates.env.filters["format_money_amount"] = format_money_amount


def utc_input(value):
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") if value else ""


def utc_display(value):
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if value else "Not recorded"


templates.env.filters["utc_input"] = utc_input
templates.env.filters["utc_display"] = utc_display
