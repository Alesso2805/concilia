from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.worksheet.worksheet import Worksheet

from concilia.reporting.domain.dashboard import AgeBucket, CreditStatus
from concilia.reporting.domain.workbook import (
    AGE_LABELS,
    REASON_LABELS,
    STATUS_LABELS,
    MatchLine,
    PeriodReport,
    neutralize,
    percent_text,
)
from concilia.shared.kernel.clock import LIMA

MONEY_FORMAT = "#,##0.00"
DATE_FORMAT = "dd/mm/yyyy"
DATETIME_FORMAT = "dd/mm/yyyy hh:mm"
BOLD = Font(bold=True)


@dataclass(frozen=True)
class Soles:
    cents: int


type Value = str | int | date | datetime | Soles | None


def _write(sheet: Worksheet, row: Sequence[Value], *, bold: bool = False) -> None:
    """Every value is written with an explicit type: text is neutralized, money is a decimal in
    soles, and times are naive Lima times because spreadsheets have no time zones."""
    cells: list[object] = []
    formats: list[str | None] = []
    for value in row:
        match value:
            case None:
                cells.append(None)
                formats.append(None)
            case Soles(cents):
                cells.append(Decimal(cents).scaleb(-2))
                formats.append(MONEY_FORMAT)
            case datetime():
                cells.append(value.astimezone(LIMA).replace(tzinfo=None))
                formats.append(DATETIME_FORMAT)
            case date():
                cells.append(value)
                formats.append(DATE_FORMAT)
            case str():
                cells.append(neutralize(value))
                formats.append(None)
            case int():
                cells.append(value)
                formats.append(None)
    sheet.append(cells)
    for cell, number_format in zip(sheet[sheet.max_row], formats, strict=False):
        if isinstance(cell.value, str):
            cell.data_type = "s"
        if number_format:
            cell.number_format = number_format
        if bold:
            cell.font = BOLD


def _summary(sheet: Worksheet, report: PeriodReport) -> None:
    dashboard = report.dashboard
    credits = dashboard.credits
    total_count = sum(tally.count for tally in credits.values())
    total_cents = sum(tally.cents for tally in credits.values())
    approved = credits[CreditStatus.APPROVED]
    for row in (
        ("Cuenta", report.account),
        ("Mes", dashboard.period.strftime("%m/%Y")),
        ("Estado del mes", "Cerrado" if dashboard.closed else "Abierto"),
        ("Antigüedad medida al", dashboard.reference_date),
        ("Generado (hora de Lima)", report.generated_at),
        ("Conciliado quiere decir", "aprobado por un revisor"),
    ):
        _write(sheet, row)
    _write(sheet, [])
    _write(sheet, ("Abonos del mes", "Abonos", "Monto"), bold=True)
    for status in (
        CreditStatus.APPROVED,
        CreditStatus.CONFIRMED,
        CreditStatus.PROPOSED,
        CreditStatus.FREE,
    ):
        tally = credits[status]
        _write(sheet, (STATUS_LABELS[status], tally.count, Soles(tally.cents)))
    _write(sheet, ("Total", total_count, Soles(total_cents)), bold=True)
    _write(sheet, ("Conciliado por monto", percent_text(approved.cents, total_cents)))
    _write(sheet, ("Conciliado por cantidad", percent_text(approved.count, total_count)))
    _write(sheet, [])
    _write(sheet, ("Pendientes por antigüedad", "Abonos", "Monto"), bold=True)
    for bucket in AgeBucket:
        tally = dashboard.pending[bucket]
        _write(sheet, (AGE_LABELS[bucket], tally.count, Soles(tally.cents)))
    _write(sheet, [])
    _write(sheet, ("Diferencias por motivo", "Coincidencias", "Monto"), bold=True)
    for item in dashboard.differences:
        _write(sheet, (REASON_LABELS.get(item.reason, item.reason), item.count, Soles(item.cents)))


MATCH_HEADERS = (
    "Fecha del abono",
    "Descripción",
    "Abonos",
    "Documentos",
    "Clientes",
    "Aplicado",
    "Diferencia",
    "Motivo",
    "Estado",
    "Origen",
    "Confirmó",
    "Confirmado el",
    "Aprobó",
    "Aprobado el",
)


def _match_row(line: MatchLine) -> tuple[Value, ...]:
    return (
        line.booked_on,
        " | ".join(line.descriptions),
        Soles(line.credits_cents),
        ", ".join(line.documents),
        ", ".join(line.customers),
        Soles(line.applied_cents),
        Soles(line.difference_cents),
        REASON_LABELS.get(line.difference_reason, "") if line.difference_reason else None,
        STATUS_LABELS.get(line.status, line.status),
        line.origin,
        line.confirmed_by,
        line.confirmed_at,
        line.approved_by,
        line.approved_at,
    )


def _matches(sheet: Worksheet, lines: Sequence[MatchLine]) -> None:
    _write(sheet, MATCH_HEADERS, bold=True)
    for line in lines:
        _write(sheet, _match_row(line))


def _pending(sheet: Worksheet, report: PeriodReport) -> None:
    reference = report.dashboard.reference_date
    _write(sheet, ("Fecha", "Descripción", "Operación", "Monto", "Estado", "Días"), bold=True)
    for line in report.pending:
        _write(
            sheet,
            (
                line.booked_on,
                line.description,
                line.operation_number,
                Soles(line.amount_cents),
                STATUS_LABELS.get(line.status, line.status),
                (reference - line.booked_on).days,
            ),
        )


SHEETS: tuple[tuple[str, Callable[[Worksheet, PeriodReport], None]], ...] = (
    ("Resumen", _summary),
    ("Conciliados", lambda sheet, report: _matches(sheet, report.reconciled)),
    ("Pendientes", _pending),
    ("Diferencias", lambda sheet, report: _matches(sheet, report.differences)),
)


def build_workbook(report: PeriodReport) -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)  # type: ignore[arg-type]
    for title, fill in SHEETS:
        fill(workbook.create_sheet(title), report)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
