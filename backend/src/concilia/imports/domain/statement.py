import hashlib
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from concilia.imports.domain.cells import (
    Cell,
    CellError,
    is_blank,
    parse_amount,
    parse_date,
    text_of,
)
from concilia.shared.kernel.normalization import extract_doc_refs, normalize_text

MAX_ROWS = 10_000
MAX_DESCRIPTION = 500


class FileError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class StatementLayout:
    date: str
    description: str
    operation_number: str | None
    amount: str | None
    debit: str | None
    credit: str | None
    skip_rows: int
    date_format: str
    decimal_separator: str
    thousands_separator: str


@dataclass(frozen=True)
class StatementLine:
    row_number: int
    booked_on: date
    amount_cents: int
    description: str
    operation_number: str | None

    @property
    def description_norm(self) -> str:
        return normalize_text(self.description)

    @property
    def doc_refs(self) -> list[str]:
        return extract_doc_refs(self.description)


@dataclass(frozen=True)
class RowError:
    row_number: int
    code: str
    cells: tuple[str, ...]


def _columns(header: Sequence[Cell], layout: StatementLayout) -> dict[str, int]:
    positions = {text_of(cell).casefold(): index for index, cell in enumerate(header)}
    wanted = {
        "date": layout.date,
        "description": layout.description,
        "operation_number": layout.operation_number,
        "amount": layout.amount,
        "debit": layout.debit,
        "credit": layout.credit,
    }
    columns = {
        field: positions[name.casefold()]
        for field, name in wanted.items()
        if name is not None and name.casefold() in positions
    }
    if len(columns) != sum(name is not None for name in wanted.values()):
        raise FileError("missing_columns")
    return columns


def _line(
    row_number: int, row: Sequence[Cell], columns: dict[str, int], layout: StatementLayout
) -> StatementLine:
    def cell(field: str) -> Cell:
        index = columns.get(field)
        return row[index] if index is not None and index < len(row) else None

    booked_on = parse_date(cell("date"), layout.date_format)
    separators = (layout.decimal_separator, layout.thousands_separator)
    if "amount" in columns:
        amount = parse_amount(cell("amount"), *separators)
    else:
        debit, credit = cell("debit"), cell("credit")
        amount = (0 if is_blank(credit) else parse_amount(credit, *separators)) - (
            0 if is_blank(debit) else abs(parse_amount(debit, *separators))
        )
    if amount == 0:
        raise CellError("zero_amount")
    description = text_of(cell("description"))
    if not description:
        raise CellError("missing_description")
    if len(description) > MAX_DESCRIPTION:
        raise CellError("description_too_long")
    operation = text_of(cell("operation_number")) or None
    return StatementLine(row_number, booked_on, amount, description, operation)


def read_statement(
    rows: Sequence[Sequence[Cell]], layout: StatementLayout
) -> list[StatementLine | RowError]:
    if len(rows) <= layout.skip_rows:
        raise FileError("missing_header")
    columns = _columns(rows[layout.skip_rows], layout)
    body = [
        (number, row)
        for number, row in enumerate(rows, start=1)
        if number > layout.skip_rows + 1 and not all(is_blank(cell) for cell in row)
    ]
    if not body:
        raise FileError("no_rows")
    if len(body) > MAX_ROWS:
        raise FileError("too_many_rows")
    lines: list[StatementLine | RowError] = []
    for number, row in body:
        try:
            lines.append(_line(number, row, columns, layout))
        except CellError as error:
            cells = tuple("" if cell is None else _shown(cell) for cell in row)
            lines.append(RowError(number, error.code, cells))
    return lines


def _shown(cell: Cell) -> str:
    try:
        return text_of(cell)
    except CellError:
        return "=…"


def fingerprints(bank_account_id: UUID, lines: Sequence[StatementLine]) -> list[str]:
    seen: Counter[tuple[date, int, str, str]] = Counter()
    result = []
    for line in lines:
        key = (
            line.booked_on,
            line.amount_cents,
            line.description_norm,
            line.operation_number or "",
        )
        occurrence = seen[key]
        seen[key] += 1
        payload = "\x1f".join(
            [str(bank_account_id), key[0].isoformat(), str(key[1]), key[2], key[3], str(occurrence)]
        )
        result.append(hashlib.sha256(payload.encode()).hexdigest())
    return result
