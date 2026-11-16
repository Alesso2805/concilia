from contextlib import AbstractAsyncContextManager
from datetime import date
from typing import Protocol
from uuid import UUID

from concilia.matching.application.runs import InvalidPeriodError, NotAllowedError, NotFoundError
from concilia.matching.domain.inbox import (
    INBOX_STATUSES,
    CreditPage,
    InboxCounts,
    MatchDetail,
    MatchFilters,
    MatchPage,
    MatchStatus,
    PeriodSummary,
)
from concilia.shared.kernel.principal import Principal

PAGE_LIMIT = 100


class InboxStore(Protocol):
    async def account_exists(self, bank_account_id: UUID) -> bool: ...

    async def periods(self, bank_account_id: UUID) -> list[PeriodSummary]: ...

    async def counts(self, bank_account_id: UUID, period: date) -> InboxCounts: ...

    async def free_credits(
        self,
        bank_account_id: UUID,
        period: date,
        filters: MatchFilters,
        after: tuple[date, UUID] | None,
        before: tuple[date, UUID] | None,
        limit: int,
    ) -> CreditPage: ...

    async def matches(
        self,
        bank_account_id: UUID,
        period: date,
        status: MatchStatus,
        filters: MatchFilters,
        after: UUID | None,
        before: UUID | None,
        limit: int,
    ) -> MatchPage: ...

    async def match_detail(self, match_id: UUID) -> MatchDetail | None: ...


class InboxTransactions(Protocol):
    def organization(self, organization_id: UUID) -> AbstractAsyncContextManager[InboxStore]: ...


def _organization(principal: Principal) -> UUID:
    if principal.organization_id is None:
        raise NotAllowedError
    return principal.organization_id


def _month(period: date) -> date:
    if period.day != 1:
        raise InvalidPeriodError
    return period


class InboxService:
    def __init__(self, transactions: InboxTransactions) -> None:
        self._transactions = transactions

    async def periods(self, principal: Principal, bank_account_id: UUID) -> list[PeriodSummary]:
        async with self._transactions.organization(_organization(principal)) as store:
            if not await store.account_exists(bank_account_id):
                raise NotFoundError
            return await store.periods(bank_account_id)

    async def counts(
        self, principal: Principal, bank_account_id: UUID, period: date
    ) -> InboxCounts:
        async with self._transactions.organization(_organization(principal)) as store:
            if not await store.account_exists(bank_account_id):
                raise NotFoundError
            return await store.counts(bank_account_id, _month(period))

    async def free_credits(
        self,
        principal: Principal,
        bank_account_id: UUID,
        period: date,
        filters: MatchFilters,
        *,
        after: tuple[date, UUID] | None = None,
        before: tuple[date, UUID] | None = None,
        limit: int = 25,
    ) -> CreditPage:
        async with self._transactions.organization(_organization(principal)) as store:
            if not await store.account_exists(bank_account_id):
                raise NotFoundError
            return await store.free_credits(
                bank_account_id, _month(period), filters, after, before, min(limit, PAGE_LIMIT)
            )

    async def matches(
        self,
        principal: Principal,
        bank_account_id: UUID,
        period: date,
        status: MatchStatus,
        filters: MatchFilters,
        *,
        after: UUID | None = None,
        before: UUID | None = None,
        limit: int = 25,
    ) -> MatchPage:
        if status not in INBOX_STATUSES:
            raise NotFoundError
        async with self._transactions.organization(_organization(principal)) as store:
            if not await store.account_exists(bank_account_id):
                raise NotFoundError
            return await store.matches(
                bank_account_id,
                _month(period),
                status,
                filters,
                after,
                before,
                min(limit, PAGE_LIMIT),
            )

    async def match_detail(self, principal: Principal, match_id: UUID) -> MatchDetail:
        async with self._transactions.organization(_organization(principal)) as store:
            detail = await store.match_detail(match_id)
        if detail is None:
            raise NotFoundError
        return detail
