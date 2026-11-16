from collections.abc import Iterable
from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


class SqlPeriodQueries:
    def __init__(self, connection: AsyncConnection) -> None:
        self._connection = connection

    async def closed_periods(self, bank_account_id: UUID, periods: Iterable[date]) -> set[date]:
        wanted = sorted(set(periods))
        if not wanted:
            return set()
        rows = await self._connection.execute(
            text(
                """SELECT period FROM period_status
                   WHERE bank_account_id = :account AND period = ANY(:periods) AND closed"""
            ),
            {"account": bank_account_id, "periods": wanted},
        )
        return set(rows.scalars())
