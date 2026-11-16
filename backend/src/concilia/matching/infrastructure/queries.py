from collections.abc import Sequence
from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

ACTIVE = ("proposed", "confirmed", "approved")
PENDING = ("proposed", "confirmed")


class SqlMatchQueries:
    """Implements imports.ActiveMatchesQuery and periods.PendingMatchesQuery."""

    def __init__(self, connection: AsyncConnection) -> None:
        self._connection = connection

    async def active(
        self, movement_ids: Sequence[UUID], receivable_ids: Sequence[UUID]
    ) -> set[UUID]:
        return await self._in_matches(movement_ids, receivable_ids, ACTIVE)

    async def pending(
        self, movement_ids: Sequence[UUID], receivable_ids: Sequence[UUID]
    ) -> set[UUID]:
        return await self._in_matches(movement_ids, receivable_ids, PENDING)

    async def any_pending(self, bank_account_id: UUID, period: date) -> bool:
        found = await self._connection.scalar(
            text(
                """SELECT EXISTS (
                       SELECT 1 FROM match_items i
                       JOIN match_status s ON s.match_id = i.match_id
                       JOIN bank_movements b ON b.id = i.bank_movement_id
                       WHERE b.bank_account_id = :account
                         AND b.booked_on >= :period
                         AND b.booked_on < CAST(:period AS date) + interval '1 month'
                         AND s.status = ANY(:statuses)
                   )"""
            ),
            {"account": bank_account_id, "period": period, "statuses": list(PENDING)},
        )
        return bool(found)

    async def _in_matches(
        self,
        movement_ids: Sequence[UUID],
        receivable_ids: Sequence[UUID],
        statuses: tuple[str, ...],
    ) -> set[UUID]:
        if not movement_ids and not receivable_ids:
            return set()
        rows = await self._connection.execute(
            text(
                """SELECT DISTINCT coalesce(i.bank_movement_id, i.receivable_id)
                   FROM match_items i JOIN match_status s ON s.match_id = i.match_id
                   WHERE s.status = ANY(:statuses)
                     AND (i.bank_movement_id = ANY(:movements)
                          OR i.receivable_id = ANY(:receivables))"""
            ),
            {
                "statuses": list(statuses),
                "movements": list(movement_ids),
                "receivables": list(receivable_ids),
            },
        )
        return set(rows.scalars())
