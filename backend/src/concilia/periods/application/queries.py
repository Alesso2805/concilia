from collections.abc import Iterable
from datetime import date
from typing import Protocol
from uuid import UUID


class PeriodQueries(Protocol):
    async def closed_periods(self, bank_account_id: UUID, periods: Iterable[date]) -> set[date]: ...
