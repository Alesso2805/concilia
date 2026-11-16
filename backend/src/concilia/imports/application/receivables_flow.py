from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol
from uuid import UUID

from concilia.banking.application.profile_config import ReceivablesConfig
from concilia.imports.application.matches import ActiveMatchesQuery
from concilia.imports.domain.model import ImportRow, RowStatus
from concilia.imports.domain.receivables import ReceivableLine, ReceivablesLayout
from concilia.imports.domain.statement import RowError


@dataclass(frozen=True)
class ExistingReceivable:
    id: UUID
    due_on: date
    amount_cents: int
    cancelled: bool


@dataclass(frozen=True)
class ReceivableChange:
    id: UUID
    due_on: date
    amount_cents: int


class ReceivableStore(Protocol):
    matches: ActiveMatchesQuery

    async def receivables_by_document(
        self, documents: list[str]
    ) -> dict[str, ExistingReceivable]: ...

    async def insert_receivables(
        self, organization_id: UUID, file_id: UUID, rows: list[ImportRow], now: datetime
    ) -> None: ...

    async def update_receivables(self, changes: list[ReceivableChange], now: datetime) -> None: ...


def receivables_layout(config: ReceivablesConfig) -> ReceivablesLayout:
    columns = config.columns
    return ReceivablesLayout(
        customer_name=columns.customer_name,
        customer_tax_id=columns.customer_tax_id,
        doc_number=columns.doc_number,
        issued_on=columns.issued_on,
        due_on=columns.due_on,
        amount=columns.amount,
        skip_rows=config.skip_rows,
        date_format=config.date_format.value,
        decimal_separator=config.decimal_separator,
        thousands_separator=config.thousands_separator,
    )


def _parsed(line: ReceivableLine) -> dict[str, Any]:
    return {
        "customer_name": line.customer_name,
        "customer_name_norm": line.customer_name_norm,
        "customer_tax_id": line.customer_tax_id,
        "doc_number": line.doc_number,
        "doc_number_norm": line.doc_number_norm,
        "issued_on": line.issued_on.isoformat(),
        "due_on": line.due_on.isoformat(),
        "amount_cents": line.amount_cents,
    }


def _classified(
    parsed: dict[str, Any], existing: ExistingReceivable | None, active: set[UUID]
) -> tuple[RowStatus, dict[str, Any]]:
    if existing is None:
        return RowStatus.OK, {**parsed, "action": "create"}
    if existing.cancelled:
        return RowStatus.CONFLICT, {**parsed, "conflict": "cancelled"}
    unchanged = (existing.due_on.isoformat(), existing.amount_cents) == (
        parsed["due_on"],
        parsed["amount_cents"],
    )
    if unchanged:
        return RowStatus.DUPLICATE, {**parsed, "action": "unchanged"}
    if existing.id in active:
        return RowStatus.CONFLICT, {**parsed, "conflict": "active_matches"}
    return RowStatus.OK, {
        **parsed,
        "action": "update",
        "receivable_id": str(existing.id),
        "previous_due_on": existing.due_on.isoformat(),
        "previous_amount_cents": existing.amount_cents,
    }


async def classify_receivables(
    store: ReceivableStore, lines: list[ReceivableLine | RowError]
) -> list[ImportRow]:
    valid = [line for line in lines if isinstance(line, ReceivableLine)]
    existing = await store.receivables_by_document([line.doc_number_norm for line in valid])
    active = await store.matches.active([], [receivable.id for receivable in existing.values()])
    rows = []
    for line in lines:
        if isinstance(line, RowError):
            rows.append(
                ImportRow(line.row_number, RowStatus.ERROR, {"cells": list(line.cells)}, line.code)
            )
            continue
        status, parsed = _classified(_parsed(line), existing.get(line.doc_number_norm), active)
        rows.append(ImportRow(line.row_number, status, parsed))
    return rows


async def apply_receivables(
    store: ReceivableStore,
    organization_id: UUID,
    file_id: UUID,
    rows: list[ImportRow],
    now: datetime,
) -> None:
    existing = await store.receivables_by_document(
        [str(row.parsed["doc_number_norm"]) for row in rows]
    )
    active = await store.matches.active([], [receivable.id for receivable in existing.values()])
    creates: list[ImportRow] = []
    changes: list[ReceivableChange] = []
    for row in rows:
        status, parsed = _classified(
            dict(row.parsed), existing.get(str(row.parsed["doc_number_norm"])), active
        )
        if status != RowStatus.OK:
            continue
        if parsed["action"] == "create":
            creates.append(row)
        else:
            changes.append(
                ReceivableChange(
                    UUID(parsed["receivable_id"]),
                    date.fromisoformat(parsed["due_on"]),
                    int(parsed["amount_cents"]),
                )
            )
    await store.insert_receivables(organization_id, file_id, creates, now)
    await store.update_receivables(changes, now)
