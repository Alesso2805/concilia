from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from concilia.reporting.domain.dashboard import CreditStatus, DayTotal, DifferenceTotal, Tally
from concilia.shared.infrastructure.db import organization_transaction

# Each live credit with the status of its active match, or `free`; a trigger keeps a credit in
# at most one active match.
CREDITS = """
    SELECT b.id, b.booked_on, b.description, b.operation_number, b.amount_cents,
           coalesce(active.status, 'free') AS status
    FROM bank_movements b
    LEFT JOIN LATERAL (
        SELECT s.status FROM match_items i JOIN match_status s ON s.match_id = i.match_id
        WHERE i.bank_movement_id = b.id AND s.status IN ('proposed', 'confirmed', 'approved')
        LIMIT 1
    ) active ON true
    WHERE b.bank_account_id = :account AND b.amount_cents > 0 AND b.voided_at IS NULL
"""


class SqlDashboardStore:
    def __init__(self, connection: AsyncConnection) -> None:
        self._connection = connection

    async def account_exists(self, bank_account_id: UUID) -> bool:
        found = await self._connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM bank_accounts WHERE id = :id)"),
            {"id": bank_account_id},
        )
        return bool(found)

    async def is_closed(self, bank_account_id: UUID, period: date) -> bool:
        closed = await self._connection.scalar(
            text(
                """SELECT closed FROM period_status
                   WHERE bank_account_id = :account AND period = :period"""
            ),
            {"account": bank_account_id, "period": period},
        )
        return bool(closed)

    async def credits_by_status(
        self, bank_account_id: UUID, start: date, end: date
    ) -> dict[CreditStatus, Tally]:
        rows = await self._connection.execute(
            text(
                f"""SELECT c.status, count(*) AS quantity, sum(c.amount_cents)::bigint AS cents
                    FROM ({CREDITS} AND b.booked_on BETWEEN :start AND :end) c
                    GROUP BY c.status"""  # noqa: S608
            ),
            {"account": bank_account_id, "start": start, "end": end},
        )
        totals = dict.fromkeys(CreditStatus, Tally())
        for row in rows:
            totals[CreditStatus(row.status)] = Tally(row.quantity, row.cents)
        return totals

    async def pending_by_day(self, bank_account_id: UUID, until: date) -> Sequence[DayTotal]:
        rows = await self._connection.execute(
            text(
                f"""SELECT c.booked_on, count(*) AS quantity, sum(c.amount_cents)::bigint AS cents
                    FROM ({CREDITS} AND b.booked_on <= :until) c
                    WHERE c.status <> 'approved'
                    GROUP BY c.booked_on"""  # noqa: S608
            ),
            {"account": bank_account_id, "until": until},
        )
        return [DayTotal(row.booked_on, row.quantity, row.cents) for row in rows]

    async def differences(
        self, bank_account_id: UUID, start: date, end: date
    ) -> list[DifferenceTotal]:
        rows = await self._connection.execute(
            text(
                """SELECT d.difference_reason AS reason, count(*) AS quantity,
                          sum(amounts.difference)::bigint AS cents
                   FROM match_status s
                   JOIN match_decisions d ON d.match_id = s.match_id AND d.action = 'confirm'
                   CROSS JOIN LATERAL (
                       SELECT coalesce(sum(b.amount_cents), 0) - coalesce(sum(i.applied_cents), 0)
                                  AS difference
                       FROM match_items i LEFT JOIN bank_movements b ON b.id = i.bank_movement_id
                       WHERE i.match_id = s.match_id
                   ) amounts
                   WHERE s.bank_account_id = :account
                     AND s.status IN ('confirmed', 'approved')
                     AND d.difference_reason IS NOT NULL
                     AND EXISTS (
                         SELECT 1 FROM match_items c
                         JOIN bank_movements b ON b.id = c.bank_movement_id
                         WHERE c.match_id = s.match_id AND b.booked_on BETWEEN :start AND :end)
                   GROUP BY d.difference_reason
                   ORDER BY d.difference_reason"""
            ),
            {"account": bank_account_id, "start": start, "end": end},
        )
        return [DifferenceTotal(row.reason, row.quantity, row.cents) for row in rows]


class SqlDashboardTransactions:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @asynccontextmanager
    async def organization(self, organization_id: UUID) -> AsyncIterator[SqlDashboardStore]:
        async with organization_transaction(self._engine, organization_id) as connection:
            yield SqlDashboardStore(connection)
