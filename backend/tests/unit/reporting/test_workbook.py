from datetime import UTC, date, datetime
from decimal import Decimal
from io import BytesIO
from uuid import uuid7

import pytest
from hypothesis import given
from hypothesis import strategies as st
from openpyxl import load_workbook

from concilia.reporting.domain.dashboard import AgeBucket, CreditStatus, Dashboard, Tally
from concilia.reporting.domain.workbook import (
    FORMULA_PREFIXES,
    MatchLine,
    PendingLine,
    PeriodReport,
    neutralize,
    percent_text,
)
from concilia.reporting.infrastructure.xlsx import build_workbook
from concilia.shared.kernel.clock import LIMA

ATTACKS = ['=HYPERLINK("http://x","clic")', "+1+1", "-2+3", "@SUM(A1)", "\tTAB", "\rCR"]


@pytest.mark.parametrize("value", ATTACKS)
def test_values_that_start_a_formula_become_text(value: str) -> None:
    assert neutralize(value) == f"'{value}"


@given(st.text(max_size=30))
def test_only_formula_starts_change(value: str) -> None:
    neutral = neutralize(value)

    if value.startswith(FORMULA_PREFIXES):
        assert neutral == f"'{value}"
    else:
        assert neutral == value


def test_percentages_round_down_to_a_tenth() -> None:
    assert (percent_text(2, 3), percent_text(1, 1), percent_text(0, 0)) == (
        "66.6 %",
        "100.0 %",
        "—",
    )


def _cell(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    """Spreadsheets have no time zones: dates and Lima times come back naive."""
    return datetime(year, month, day, hour, minute, tzinfo=LIMA).replace(tzinfo=None)


def _exact(value: object) -> object:
    """Spreadsheets store numbers as binary floats; compare them as exact decimals."""
    return Decimal(str(value)) if isinstance(value, int | float) else value


def _report() -> PeriodReport:
    line = MatchLine(
        match_id=uuid7(),
        status="approved",
        source="engine",
        rule="R1",
        booked_on=date(2027, 1, 5),
        descriptions=["=HYPERLINK(1)"],
        credits_cents=118_050,
        documents=["F001-123"],
        customers=["@Cliente"],
        applied_cents=118_000,
        difference_reason="rounding",
        confirmed_by="Ana",
        confirmed_at=datetime(2027, 1, 6, 4, 30, tzinfo=UTC),
        approved_by="Beto",
        approved_at=datetime(2027, 1, 7, 15, 0, tzinfo=UTC),
    )
    return PeriodReport(
        account="BCP · Principal (1234)",
        generated_at=datetime(2027, 2, 3, 15, 0, tzinfo=UTC),
        dashboard=Dashboard(
            period=date(2027, 1, 1),
            reference_date=date(2027, 1, 31),
            closed=True,
            credits={
                CreditStatus.FREE: Tally(1, 1_250),
                CreditStatus.PROPOSED: Tally(),
                CreditStatus.CONFIRMED: Tally(),
                CreditStatus.APPROVED: Tally(1, 118_050),
            },
            pending=dict.fromkeys(AgeBucket, Tally()),
        ),
        reconciled=[line],
        pending=[PendingLine(date(2027, 1, 20), "-cargo", None, 1_250, "free")],
        differences=[line],
    )


def test_the_workbook_has_four_sheets_with_typed_cells() -> None:
    workbook = load_workbook(BytesIO(build_workbook(_report())))

    assert workbook.sheetnames == ["Resumen", "Conciliados", "Pendientes", "Diferencias"]
    [reconciled] = [
        tuple(_exact(value) for value in row)
        for row in workbook["Conciliados"].iter_rows(min_row=2, values_only=True)
    ]
    assert reconciled == (
        _cell(2027, 1, 5),
        "'=HYPERLINK(1)",
        Decimal("1180.5"),
        "F001-123",
        "'@Cliente",
        Decimal("1180"),
        Decimal("0.5"),
        "Redondeo",
        "Aprobado",
        "Motor (R1)",
        "Ana",
        _cell(2027, 1, 5, 23, 30),
        "Beto",
        _cell(2027, 1, 7, 10, 0),
    )
    pending = workbook["Pendientes"]
    assert [_exact(cell.value) for cell in pending[2]] == [
        _cell(2027, 1, 20),
        "'-cargo",
        None,
        Decimal("12.5"),
        "Sin conciliar",
        Decimal("11"),
    ]
    assert pending["B2"].data_type == "s"
    assert pending["D2"].number_format == "#,##0.00"


def test_no_cell_of_the_workbook_is_a_formula() -> None:
    workbook = load_workbook(BytesIO(build_workbook(_report())))

    cells = [cell for sheet in workbook for row in sheet.iter_rows() for cell in row]
    assert cells
    assert all(cell.data_type != "f" for cell in cells)
