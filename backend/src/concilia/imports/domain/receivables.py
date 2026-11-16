import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from concilia.imports.domain.cells import (
    Cell,
    CellError,
    is_blank,
    parse_amount,
    parse_date,
    text_of,
)
from concilia.imports.domain.statement import MAX_ROWS, FileError, RowError
from concilia.shared.kernel.normalization import normalize_doc_number, normalize_text

MAX_CUSTOMER = 200
MAX_DOCUMENT = 40
TAX_ID = re.compile(r"[0-9]{8}|[0-9]{11}")
TAX_ID_NOISE = re.compile(r"[\s.-]")


@dataclass(frozen=True)
class ReceivablesLayout:
    customer_name: str
    customer_tax_id: str | None
    doc_number: str
    issued_on: str
    due_on: str
    amount: str
    skip_rows: int
    date_format: str
    decimal_separator: str
    thousands_separator: str


@dataclass(frozen=True)
class ReceivableLine:
    row_number: int
    customer_name: str
    customer_tax_id: str | None
    doc_number: str
    doc_number_norm: str
    issued_on: date
    due_on: date
    amount_cents: int

    @property
    def customer_name_norm(self) -> str:
        return normalize_text(self.customer_name)


def _columns(header: Sequence[Cell], layout: ReceivablesLayout) -> dict[str, int]:
    positions = {text_of(cell).casefold(): index for index, cell in enumerate(header)}
    wanted = {
        "customer_name": layout.customer_name,
        "customer_tax_id": layout.customer_tax_id,
        "doc_number": layout.doc_number,
        "issued_on": layout.issued_on,
        "due_on": layout.due_on,
        "amount": layout.amount,
    }
    columns = {
        field: positions[name.casefold()]
        for field, name in wanted.items()
        if name is not None and name.casefold() in positions
    }
    if len(columns) != sum(name is not None for name in wanted.values()):
        raise FileError("missing_columns")
    return columns


def _tax_id(cell: Cell) -> str | None:
    text = TAX_ID_NOISE.sub("", text_of(cell))
    if not text:
        return None
    if TAX_ID.fullmatch(text) is None:
        raise CellError("invalid_tax_id")
    return text


def _line(
    row_number: int, row: Sequence[Cell], columns: dict[str, int], layout: ReceivablesLayout
) -> ReceivableLine:
    def cell(field: str) -> Cell:
        index = columns.get(field)
        return row[index] if index is not None and index < len(row) else None

    customer = text_of(cell("customer_name"))
    if not customer:
        raise CellError("missing_customer")
    if len(customer) > MAX_CUSTOMER:
        raise CellError("customer_too_long")
    document = text_of(cell("doc_number"))
    if not document:
        raise CellError("missing_document")
    normalized = normalize_doc_number(document)
    if normalized is None or len(document) > MAX_DOCUMENT:
        raise CellError("invalid_document")
    issued_on = parse_date(cell("issued_on"), layout.date_format)
    due_on = parse_date(cell("due_on"), layout.date_format)
    if due_on < issued_on:
        raise CellError("due_before_issue")
    amount = parse_amount(cell("amount"), layout.decimal_separator, layout.thousands_separator)
    if amount <= 0:
        raise CellError("non_positive_amount")
    tax_id = _tax_id(cell("customer_tax_id")) if "customer_tax_id" in columns else None
    return ReceivableLine(
        row_number, customer, tax_id, document, normalized, issued_on, due_on, amount
    )


def _shown(row: Sequence[Cell]) -> tuple[str, ...]:
    shown = []
    for cell in row:
        try:
            shown.append(text_of(cell))
        except CellError:
            shown.append("=…")
    return tuple(shown)


def read_receivables(
    rows: Sequence[Sequence[Cell]], layout: ReceivablesLayout
) -> list[ReceivableLine | RowError]:
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
    lines: list[ReceivableLine | RowError] = []
    seen: set[str] = set()
    for number, row in body:
        try:
            line = _line(number, row, columns, layout)
            if line.doc_number_norm in seen:
                raise CellError("repeated_document")
            seen.add(line.doc_number_norm)
            lines.append(line)
        except CellError as error:
            lines.append(RowError(number, error.code, _shown(row)))
    return lines
