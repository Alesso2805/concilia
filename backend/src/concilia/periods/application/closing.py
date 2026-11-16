from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from uuid import UUID, uuid7

from concilia.audit.application.recorder import AuditAction, AuditEvent, AuditRecorder
from concilia.periods.application.pending import PendingMatchesQuery
from concilia.periods.domain.period import (
    PeriodAction,
    PeriodError,
    PeriodState,
    RoleRequiredError,
    check_period_action,
)
from concilia.shared.kernel.clock import Clock
from concilia.shared.kernel.ids import create_or_replay, validate_client_id
from concilia.shared.kernel.principal import Principal

__all__ = [
    "AccountNotFoundError",
    "PeriodAction",
    "PeriodError",
    "PeriodEvent",
    "PeriodService",
    "PeriodStore",
    "PeriodTransactions",
]

AUDIT_ACTIONS = {
    PeriodAction.CLOSE: AuditAction.PERIOD_CLOSED,
    PeriodAction.REOPEN: AuditAction.PERIOD_REOPENED,
}


class AccountNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class PeriodEvent:
    id: UUID
    bank_account_id: UUID
    period: date
    action: PeriodAction
    reason: str | None
    decided_by: UUID
    decided_at: datetime


class PeriodStore(Protocol):
    audit: AuditRecorder
    pending: PendingMatchesQuery

    async def lock_organization(self, organization_id: UUID) -> None: ...

    async def account_exists(self, bank_account_id: UUID) -> bool: ...

    async def is_closed(self, bank_account_id: UUID, period: date) -> bool: ...

    async def find_event(self, event_id: UUID) -> PeriodEvent | None: ...

    async def insert_event(self, organization_id: UUID, event: PeriodEvent) -> None: ...


class PeriodTransactions(Protocol):
    def organization(self, organization_id: UUID) -> AbstractAsyncContextManager[PeriodStore]: ...


def _text(value: str | None) -> str | None:
    stripped = (value or "").strip()
    return stripped or None


class PeriodService:
    def __init__(self, transactions: PeriodTransactions, clock: Clock) -> None:
        self._transactions = transactions
        self._clock = clock

    async def decide(
        self,
        principal: Principal,
        event_id: UUID,
        bank_account_id: UUID,
        period: date,
        action: PeriodAction,
        reason: str | None,
    ) -> tuple[PeriodEvent, bool]:
        organization_id = principal.organization_id
        if organization_id is None:
            raise RoleRequiredError
        now = self._clock.now()
        validate_client_id(event_id, now)
        async with self._transactions.organization(organization_id) as store:
            await store.lock_organization(organization_id)

            async def create() -> PeriodEvent:
                return await self.apply(
                    store,
                    organization_id,
                    bank_account_id,
                    period,
                    action,
                    reason,
                    actor=principal.user_id,
                    roles=principal.roles,
                    event_id=event_id,
                )

            def same_content(existing: PeriodEvent) -> bool:
                return (
                    existing.bank_account_id,
                    existing.period,
                    existing.action,
                    existing.reason,
                    existing.decided_by,
                ) == (bank_account_id, period, action, _text(reason), principal.user_id)

            return await create_or_replay(
                find=lambda: store.find_event(event_id), create=create, same_content=same_content
            )

    async def apply(
        self,
        store: PeriodStore,
        organization_id: UUID,
        bank_account_id: UUID,
        period: date,
        action: PeriodAction,
        reason: str | None,
        *,
        actor: UUID,
        roles: frozenset[str],
        event_id: UUID | None = None,
    ) -> PeriodEvent:
        """Checks and records one close or reopen; the caller holds the organization lock."""
        if not await store.account_exists(bank_account_id):
            raise AccountNotFoundError
        state = PeriodState(
            closed=await store.is_closed(bank_account_id, period),
            has_pending_matches=await store.pending.any_pending(bank_account_id, period),
        )
        check_period_action(action, period, self._clock.today_lima(), state, _text(reason), roles)
        event = PeriodEvent(
            event_id or uuid7(),
            bank_account_id,
            period,
            action,
            _text(reason),
            actor,
            self._clock.now(),
        )
        await store.insert_event(organization_id, event)
        await store.audit.record(
            AuditEvent(
                id=uuid7(),
                organization_id=organization_id,
                actor_user_id=actor,
                action=AUDIT_ACTIONS[action],
                entity="period_event",
                entity_id=event.id,
                at=event.decided_at,
            )
        )
        return event
