import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

CENTS_PER_SOL = 100
MAX_DECIMALS = 2
CURRENCY_MARKS = ("S/.", "S/", "PEN")


@dataclass(frozen=True)
class Formula:
    """An Excel cell that holds a formula. Formulas are never evaluated."""


type Cell = str | date | Decimal | Formula | None


class CellError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


DATE_PATTERNS = {
    "DD/MM/YYYY": re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})"),
    "DD-MM-YYYY": re.compile(r"(\d{1,2})-(\d{1,2})-(\d{4})"),
    "DD/MM/YY": re.compile(r"(\d{1,2})/(\d{1,2})/(\d{2})"),
    "YYYY-MM-DD": re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})"),
}


def is_blank(cell: Cell) -> bool:
    return cell is None or (isinstance(cell, str) and not cell.strip())


def text_of(cell: Cell) -> str:
    if isinstance(cell, Formula):
        raise CellError("formula_not_allowed")
    if isinstance(cell, datetime):
        return cell.date().isoformat()
    return "" if cell is None else str(cell).strip()


def parse_date(cell: Cell, date_format: str) -> date:
    if isinstance(cell, Formula):
        raise CellError("formula_not_allowed")
    if isinstance(cell, datetime):
        return cell.date()
    if isinstance(cell, date):
        return cell
    text = text_of(cell)
    if not text:
        raise CellError("missing_date")
    match = DATE_PATTERNS[date_format].fullmatch(text)
    if match is None:
        raise CellError("invalid_date")
    parts = [int(group) for group in match.groups()]
    if date_format == "YYYY-MM-DD":
        year, month, day = parts
    else:
        day, month, year = parts
        if date_format == "DD/MM/YY":
            year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        raise CellError("invalid_date") from None


def _cents_of_decimal(value: Decimal) -> int:
    scaled = value * CENTS_PER_SOL
    if scaled != scaled.to_integral_value():
        raise CellError("too_many_decimals")
    return int(scaled)


def parse_amount(cell: Cell, decimal_separator: str, thousands_separator: str) -> int:
    if isinstance(cell, Formula):
        raise CellError("formula_not_allowed")
    if isinstance(cell, Decimal):
        return _cents_of_decimal(cell)
    text = text_of(cell).replace("\xa0", " ")
    for mark in CURRENCY_MARKS:
        text = text.replace(mark, "")
    text = text.strip()
    if not text:
        raise CellError("missing_amount")
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1].strip()
    if text[:1] in "+-":
        negative, text = negative or text[0] == "-", text[1:].strip()
    elif text.endswith("-"):
        negative, text = True, text[:-1].strip()
    if thousands_separator:
        text = text.replace(thousands_separator, "")
    whole, separator, fraction = text.partition(decimal_separator)
    if (
        not whole.isascii()
        or not whole.isdigit()
        or (separator and (not fraction.isascii() or not fraction.isdigit()))
    ):
        raise CellError("invalid_amount")
    if len(fraction) > MAX_DECIMALS:
        raise CellError("too_many_decimals")
    cents = int(whole) * CENTS_PER_SOL + int(fraction.ljust(MAX_DECIMALS, "0"))
    return -cents if negative else cents
