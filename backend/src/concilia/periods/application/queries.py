from collections.abc import Iterable
from datetime import date
from typing import Protocol
from uuid import UUID

from concilia.periods.domain.period import period_of

__all__ = ["PeriodQueries", "period_of"]


class PeriodQueries(Protocol):
    async def closed_periods(self, bank_account_id: UUID, periods: Iterable[date]) -> set[date]: ...
