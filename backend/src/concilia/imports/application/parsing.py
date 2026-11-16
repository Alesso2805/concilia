from collections.abc import Sequence
from typing import Any
from uuid import UUID

from concilia.banking.application.profile_config import ReceivablesConfig, StatementConfig
from concilia.imports.application.receivables_flow import receivable_parsed, receivables_layout
from concilia.imports.domain.cells import Cell
from concilia.imports.domain.model import ImportRow, RowStatus
from concilia.imports.domain.receivables import ReceivableLine, read_receivables
from concilia.imports.domain.statement import (
    StatementLayout,
    StatementLine,
    fingerprints,
    read_statement,
)


class UnreadableRowsError(ValueError):
    """A file that has to be fully valid, such as a demo file, has rows with errors."""


def statement_layout(config: StatementConfig) -> StatementLayout:
    columns = config.columns
    return StatementLayout(
        date=columns.date,
        description=columns.description,
        operation_number=columns.operation_number,
        amount=columns.amount,
        debit=columns.debit,
        credit=columns.credit,
        skip_rows=config.skip_rows,
        date_format=config.date_format.value,
        decimal_separator=config.decimal_separator,
        thousands_separator=config.thousands_separator,
    )


def statement_parsed(line: StatementLine, fingerprint: str) -> dict[str, Any]:
    return {
        "booked_on": line.booked_on.isoformat(),
        "amount_cents": line.amount_cents,
        "description": line.description,
        "operation_number": line.operation_number,
        "fingerprint": fingerprint,
    }


def statement_rows(
    cells: Sequence[Sequence[Cell]], config: StatementConfig, bank_account_id: UUID
) -> list[ImportRow]:
    """Every row of a statement as it would be confirmed into an empty account."""
    lines = read_statement(cells, statement_layout(config))
    valid = [line for line in lines if isinstance(line, StatementLine)]
    if len(valid) != len(lines):
        raise UnreadableRowsError
    return [
        ImportRow(line.row_number, RowStatus.OK, statement_parsed(line, fingerprint))
        for line, fingerprint in zip(valid, fingerprints(bank_account_id, valid), strict=True)
    ]


def receivable_rows(cells: Sequence[Sequence[Cell]], config: ReceivablesConfig) -> list[ImportRow]:
    """Every row of a receivables file as it would create receivables in an empty organization."""
    lines = read_receivables(cells, receivables_layout(config))
    valid = [line for line in lines if isinstance(line, ReceivableLine)]
    if len(valid) != len(lines):
        raise UnreadableRowsError
    return [
        ImportRow(line.row_number, RowStatus.OK, {**receivable_parsed(line), "action": "create"})
        for line in valid
    ]
