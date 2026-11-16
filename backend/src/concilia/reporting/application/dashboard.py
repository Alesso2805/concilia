from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from datetime import date
from typing import Protocol
from uuid import UUID

from concilia.reporting.domain.dashboard import (
    AgeBucket,
    CreditStatus,
    Dashboard,
    DayTotal,
    DifferenceTotal,
    Tally,
    age_pending,
    month_end,
    reference_date,
)
from concilia.shared.kernel.clock import Clock
from concilia.shared.kernel.principal import Principal

__all__ = [
    "AgeBucket",
    "CreditStatus",
    "Dashboard",
    "DashboardService",
    "DashboardStore",
    "DashboardTransactions",
    "InvalidPeriodError",
    "NotAllowedError",
    "NotFoundError",
    "Tally",
    "load_dashboard",
]

VIEWER_ROLES = frozenset({"admin", "analyst", "reviewer"})


class NotAllowedError(Exception):
    pass


class NotFoundError(Exception):
    pass


class InvalidPeriodError(Exception):
    pass


class DashboardStore(Protocol):
    async def account_exists(self, bank_account_id: UUID) -> bool: ...

    async def is_closed(self, bank_account_id: UUID, period: date) -> bool: ...

    async def credits_by_status(
        self, bank_account_id: UUID, start: date, end: date
    ) -> dict[CreditStatus, Tally]: ...

    async def pending_by_day(self, bank_account_id: UUID, until: date) -> Sequence[DayTotal]: ...

    async def differences(
        self, bank_account_id: UUID, start: date, end: date
    ) -> list[DifferenceTotal]: ...


class DashboardTransactions(Protocol):
    def organization(
        self, organization_id: UUID
    ) -> AbstractAsyncContextManager[DashboardStore]: ...


async def load_dashboard(
    store: DashboardStore, bank_account_id: UUID, period: date, today: date
) -> Dashboard:
    reference = reference_date(period, today)
    end = month_end(period)
    return Dashboard(
        period=period,
        reference_date=reference,
        closed=await store.is_closed(bank_account_id, period),
        credits=await store.credits_by_status(bank_account_id, period, end),
        pending=age_pending(await store.pending_by_day(bank_account_id, reference), reference),
        differences=await store.differences(bank_account_id, period, end),
    )


class DashboardService:
    def __init__(self, transactions: DashboardTransactions, clock: Clock) -> None:
        self._transactions = transactions
        self._clock = clock

    async def dashboard(
        self, principal: Principal, bank_account_id: UUID, period: date
    ) -> Dashboard:
        """The month's credits by status; credits not yet approved up to the reference date, of
        this and earlier months, by age; and confirmed differences by reason."""
        if principal.organization_id is None or not principal.roles & VIEWER_ROLES:
            raise NotAllowedError
        if period.day != 1:
            raise InvalidPeriodError
        async with self._transactions.organization(principal.organization_id) as store:
            if not await store.account_exists(bank_account_id):
                raise NotFoundError
            return await load_dashboard(store, bank_account_id, period, self._clock.today_lima())
