from collections.abc import Sequence
from datetime import UTC, date, datetime
from uuid import UUID, uuid7

import pytest

from concilia.imports.application.matches import ActiveMatchesQuery
from concilia.imports.application.receivables_flow import (
    ExistingReceivable,
    ReceivableChange,
    apply_receivables,
    classify_receivables,
)
from concilia.imports.domain.model import ImportRow, RowStatus
from concilia.imports.domain.receivables import ReceivableLine
from concilia.imports.domain.statement import RowError

pytestmark = pytest.mark.anyio

NOW = datetime(2027, 2, 3, 15, 0, tzinfo=UTC)


class Matches:
    def __init__(self, busy: set[UUID]) -> None:
        self.busy = busy

    async def active(
        self, movement_ids: Sequence[UUID], receivable_ids: Sequence[UUID]
    ) -> set[UUID]:
        return self.busy & set(receivable_ids)

    async def pending(
        self, movement_ids: Sequence[UUID], receivable_ids: Sequence[UUID]
    ) -> set[UUID]:
        return self.busy & set(receivable_ids)


class Store:
    def __init__(self, existing: dict[str, ExistingReceivable], busy: set[UUID]) -> None:
        self.existing = existing
        self.matches: ActiveMatchesQuery = Matches(busy)
        self.created: list[str] = []
        self.changes: list[ReceivableChange] = []

    async def receivables_by_document(self, documents: list[str]) -> dict[str, ExistingReceivable]:
        return {doc: self.existing[doc] for doc in documents if doc in self.existing}

    async def insert_receivables(
        self, organization_id: UUID, file_id: UUID, rows: list[ImportRow], now: datetime
    ) -> None:
        self.created += [str(row.parsed["doc_number_norm"]) for row in rows]

    async def update_receivables(self, changes: list[ReceivableChange], now: datetime) -> None:
        self.changes += changes


def _line(row_number: int, document: str, amount_cents: int) -> ReceivableLine:
    return ReceivableLine(
        row_number,
        "Gloria SA",
        None,
        document,
        document,
        date(2027, 1, 2),
        date(2027, 2, 15),
        amount_cents,
    )


def _existing(amount_cents: int, cancelled: bool = False) -> ExistingReceivable:
    return ExistingReceivable(uuid7(), date(2027, 2, 15), amount_cents, cancelled)


async def test_rows_are_classified_against_the_stored_receivables() -> None:
    busy = _existing(100)
    store = Store(
        {
            "F001-2": _existing(200),
            "F001-3": _existing(300),
            "F001-4": _existing(999, cancelled=True),
            "F001-5": busy,
        },
        {busy.id},
    )
    lines: list[ReceivableLine | RowError] = [
        _line(2, "F001-1", 100),
        _line(3, "F001-2", 200),
        _line(4, "F001-3", 350),
        _line(5, "F001-4", 400),
        _line(6, "F001-5", 500),
        RowError(7, "missing_amount", ("Gloria SA", "F001-6", "")),
    ]

    rows = await classify_receivables(store, lines)

    assert [
        (row.status, row.parsed.get("action") or row.parsed.get("conflict") or row.error_code)
        for row in rows
    ] == [
        (RowStatus.OK, "create"),
        (RowStatus.DUPLICATE, "unchanged"),
        (RowStatus.OK, "update"),
        (RowStatus.CONFLICT, "cancelled"),
        (RowStatus.CONFLICT, "active_matches"),
        (RowStatus.ERROR, "missing_amount"),
    ]
    assert rows[2].parsed["previous_amount_cents"] == 300


async def test_confirming_reclassifies_rows_that_changed_since_the_preview() -> None:
    preview = Store({"F001-2": _existing(200)}, set())
    rows = [
        row
        for row in await classify_receivables(
            preview, [_line(2, "F001-1", 100), _line(3, "F001-2", 250)]
        )
        if row.status == RowStatus.OK
    ]
    changed = preview.existing["F001-2"]
    now_busy = Store({"F001-1": _existing(100), "F001-2": changed}, {changed.id})

    await apply_receivables(now_busy, uuid7(), uuid7(), rows, NOW)

    assert now_busy.created == []
    assert now_busy.changes == []
