from decimal import Decimal, InvalidOperation

from fastapi.templating import Jinja2Templates


templates = Jinja2Templates(directory="app/templates")


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
