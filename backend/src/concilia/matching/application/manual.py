from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid7

from concilia.audit.application.recorder import AuditAction, AuditEvent
from concilia.matching.application.decisions import DecisionStore, MatchDecisionService
from concilia.matching.application.runs import NotAllowedError, NotFoundError
from concilia.matching.domain.decisions import Action, DecisionError, DecisionRequest
from concilia.matching.domain.manual import ManualApplication, ManualMatch, check_manual_match
from concilia.matching.domain.model import DifferenceReason
from concilia.shared.kernel.clock import Clock
from concilia.shared.kernel.ids import create_or_replay, validate_client_id
from concilia.shared.kernel.principal import Principal

__all__ = [
    "CreditNotFreeError",
    "InsufficientBalanceError",
    "ManualApplication",
    "ManualMatch",
    "ManualMatchService",
    "ManualStore",
    "StoredManualMatch",
]

ANALYST = "analyst"


class CreditNotFreeError(DecisionError):
    code = "credit_not_free"


class InsufficientBalanceError(DecisionError):
    code = "insufficient_balance"


@dataclass(frozen=True)
class CreditFacts:
    id: UUID
    bank_account_id: UUID
    live_credit: bool
    free: bool


@dataclass(frozen=True)
class ReceivableFacts:
    id: UUID
    cancelled: bool
    available_cents: int


@dataclass(frozen=True)
class StoredManualMatch:
    id: UUID
    bank_account_id: UUID
    created_by: UUID | None
    match: ManualMatch


class ManualStore(DecisionStore, Protocol):
    async def credit_facts(self, credit_ids: list[UUID]) -> list[CreditFacts]: ...

    async def receivable_facts(self, receivable_ids: list[UUID]) -> list[ReceivableFacts]: ...

    async def find_manual_match(self, match_id: UUID) -> StoredManualMatch | None: ...

    async def insert_manual_match(
        self, organization_id: UUID, stored: StoredManualMatch, now: datetime
    ) -> None: ...


class ManualTransactions(Protocol):
    def organization(self, organization_id: UUID) -> AbstractAsyncContextManager[ManualStore]: ...


def _same(stored: StoredManualMatch, candidate: StoredManualMatch) -> bool:
    return (
        stored.bank_account_id == candidate.bank_account_id
        and stored.created_by == candidate.created_by
        and set(stored.match.credit_ids) == set(candidate.match.credit_ids)
        and set(stored.match.applications) == set(candidate.match.applications)
    )


class ManualMatchService:
    def __init__(
        self, transactions: ManualTransactions, decisions: MatchDecisionService, clock: Clock
    ) -> None:
        self._transactions = transactions
        self._decisions = decisions
        self._clock = clock

    async def create(
        self,
        principal: Principal,
        match_id: UUID,
        bank_account_id: UUID,
        match: ManualMatch,
        *,
        difference_reason: DifferenceReason | None = None,
        difference_note: str | None = None,
    ) -> tuple[StoredManualMatch, bool]:
        """An analyst's match, confirmed by them in the same transaction (SPEC). Applied amounts
        below a receivable's available balance leave it partially paid."""
        organization_id = principal.organization_id
        if organization_id is None or ANALYST not in principal.roles:
            raise NotAllowedError
        now = self._clock.now()
        validate_client_id(match_id, now)
        check_manual_match(match)
        candidate = StoredManualMatch(match_id, bank_account_id, principal.user_id, match)
        async with self._transactions.organization(organization_id) as store:
            await store.lock_organization(organization_id)

            async def create() -> StoredManualMatch:
                await self._check_items(store, bank_account_id, match)
                await store.insert_manual_match(organization_id, candidate, now)
                await store.audit.record(
                    AuditEvent(
                        id=uuid7(),
                        organization_id=organization_id,
                        actor_user_id=principal.user_id,
                        action=AuditAction.MATCH_CREATED,
                        entity="match",
                        entity_id=match_id,
                        at=now,
                        metadata={"source": "manual"},
                    )
                )
                request = DecisionRequest(
                    Action.CONFIRM,
                    difference_reason=difference_reason,
                    difference_note=difference_note,
                )
                await self._decisions.apply(
                    store,
                    organization_id,
                    match_id,
                    request,
                    actor=principal.user_id,
                    roles=principal.roles,
                    now=now,
                )
                return candidate

            return await create_or_replay(
                find=lambda: store.find_manual_match(match_id),
                create=create,
                same_content=lambda stored: _same(stored, candidate),
            )

    async def _check_items(
        self, store: ManualStore, bank_account_id: UUID, match: ManualMatch
    ) -> None:
        credits = await store.credit_facts(list(match.credit_ids))
        if len(credits) != len(match.credit_ids):
            raise NotFoundError
        if any(
            credit.bank_account_id != bank_account_id or not credit.live_credit or not credit.free
            for credit in credits
        ):
            raise CreditNotFreeError
        applied = {a.receivable_id: a.applied_cents for a in match.applications}
        receivables = await store.receivable_facts(list(applied))
        if len(receivables) != len(applied):
            raise NotFoundError
        if any(
            receivable.cancelled or applied[receivable.id] > receivable.available_cents
            for receivable in receivables
        ):
            raise InsufficientBalanceError
