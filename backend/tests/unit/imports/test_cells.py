from datetime import date, datetime
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from concilia.imports.domain.cells import Cell, CellError, Formula, parse_amount, parse_date


@pytest.mark.parametrize(
    ("cell", "decimal", "thousands", "cents"),
    [
        ("1234.56", ".", "", 123_456),
        ("1,234.56", ".", ",", 123_456),
        ("1.234,56", ",", ".", 123_456),
        ("-1.234,5", ",", ".", -123_450),
        ("(250.00)", ".", ",", -25_000),
        ("250.00-", ".", ",", -25_000),
        ("+3", ".", "", 300),
        ("S/ 1,000.00", ".", ",", 100_000),
        ("1 234,56", ",", " ", 123_456),
        (Decimal("1234.5"), ",", ".", 123_450),
        (Decimal("-0.01"), ".", "", -1),
    ],
)
def test_amounts_become_integer_cents(cell: Cell, decimal: str, thousands: str, cents: int) -> None:
    assert parse_amount(cell, decimal, thousands) == cents


@pytest.mark.parametrize(
    ("cell", "code"),
    [
        ("", "missing_amount"),
        (None, "missing_amount"),
        ("12.345", "too_many_decimals"),
        (Decimal("1.005"), "too_many_decimals"),
        ("doce", "invalid_amount"),
        ("1.2.3", "invalid_amount"),
        ("\uff11\uff12", "invalid_amount"),
        (Formula(), "formula_not_allowed"),
    ],
)
def test_malformed_amounts_are_row_errors(cell: Cell, code: str) -> None:
    with pytest.raises(CellError) as error:
        parse_amount(cell, ".", ",")
    assert error.value.code == code


@given(st.integers(min_value=-(10**12), max_value=10**12))
def test_written_amounts_read_back_exactly(cents: int) -> None:
    whole, rest = divmod(abs(cents), 100)
    text = f"{'-' if cents < 0 else ''}{whole:,}.{rest:02d}"

    assert parse_amount(text, ".", ",") == cents
    assert (
        parse_amount(text.replace(",", "_").replace(".", ",").replace("_", "."), ",", ".") == cents
    )


@pytest.mark.parametrize(
    ("cell", "date_format", "expected"),
    [
        ("29/02/2028", "DD/MM/YYYY", date(2028, 2, 29)),
        ("1-3-2027", "DD-MM-YYYY", date(2027, 3, 1)),
        ("31/12/26", "DD/MM/YY", date(2026, 12, 31)),
        ("2027-01-31", "YYYY-MM-DD", date(2027, 1, 31)),
        (date(2027, 1, 5), "DD/MM/YYYY", date(2027, 1, 5)),
        (datetime(2027, 1, 5, 0, 0), "DD/MM/YYYY", date(2027, 1, 5)),  # noqa: DTZ001 - openpyxl reads naive datetimes
    ],
)
def test_dates_follow_the_profile_format(cell: Cell, date_format: str, expected: date) -> None:
    assert parse_date(cell, date_format) == expected


@pytest.mark.parametrize(
    ("cell", "code"),
    [
        ("29/02/2027", "invalid_date"),
        ("2027-01-31", "invalid_date"),
        ("", "missing_date"),
        (Formula(), "formula_not_allowed"),
    ],
)
def test_bad_dates_are_row_errors(cell: Cell, code: str) -> None:
    with pytest.raises(CellError) as error:
        parse_date(cell, "DD/MM/YYYY")
    assert error.value.code == code
