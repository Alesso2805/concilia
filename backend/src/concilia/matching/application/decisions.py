from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid7

from concilia.audit.application.recorder import AuditAction, AuditEvent, AuditRecorder
from concilia.matching.application.runs import NotAllowedError, NotFoundError
from concilia.matching.domain.decisions import (
    Action,
    DecisionError,
    DecisionRequest,
    MatchState,
    check_decision,
)
from concilia.matching.domain.model import DifferenceReason
from concilia.shared.kernel.clock import Clock
from concilia.shared.kernel.ids import create_or_replay, validate_client_id
from concilia.shared.kernel.principal import Principal

__all__ = [
    "Action",
    "DecisionError",
    "DecisionRequest",
    "DecisionStore",
    "DecisionTransactions",
    "DifferenceReason",
    "MatchDecisionService",
    "StoredDecision",
]

AUDIT_ACTIONS = {
    Action.CONFIRM: AuditAction.MATCH_CONFIRMED,
    Action.DISCARD: AuditAction.MATCH_DISCARDED,
    Action.APPROVE: AuditAction.MATCH_APPROVED,
    Action.REJECT: AuditAction.MATCH_REJECTED,
    Action.REVERT: AuditAction.MATCH_REVERTED,
}


@dataclass(frozen=True)
class StoredDecision:
    id: UUID
    match_id: UUID
    action: Action
    reason: str | None
    difference_reason: DifferenceReason | None
    difference_note: str | None
    decided_by: UUID
    decided_at: datetime


class DecisionStore(Protocol):
    audit: AuditRecorder

    async def lock_organization(self, organization_id: UUID) -> None: ...

    async def match_state(self, match_id: UUID) -> MatchState | None: ...

    async def find_decision(self, decision_id: UUID) -> StoredDecision | None: ...

    async def insert_decision(self, organization_id: UUID, decision: StoredDecision) -> None: ...


class DecisionTransactions(Protocol):
    def organization(self, organization_id: UUID) -> AbstractAsyncContextManager[DecisionStore]: ...


def _text(value: str | None) -> str | None:
    stripped = (value or "").strip()
    return stripped or None


class MatchDecisionService:
    def __init__(self, transactions: DecisionTransactions, clock: Clock) -> None:
        self._transactions = transactions
        self._clock = clock

    async def decide(
        self, principal: Principal, match_id: UUID, decision_id: UUID, request: DecisionRequest
    ) -> tuple[StoredDecision, bool]:
        organization_id = principal.organization_id
        if organization_id is None:
            raise NotAllowedError
        now = self._clock.now()
        validate_client_id(decision_id, now)
        async with self._transactions.organization(organization_id) as store:
            await store.lock_organization(organization_id)

            async def create() -> StoredDecision:
                return await self.apply(
                    store,
                    organization_id,
                    match_id,
                    request,
                    actor=principal.user_id,
                    roles=principal.roles,
                    decision_id=decision_id,
                    now=now,
                )

            def same_content(existing: StoredDecision) -> bool:
                return (
                    existing.match_id,
                    existing.action,
                    existing.reason,
                    existing.difference_reason,
                    existing.difference_note,
                    existing.decided_by,
                ) == (
                    match_id,
                    request.action,
                    _text(request.reason),
                    request.difference_reason,
                    _text(request.difference_note),
                    principal.user_id,
                )

            return await create_or_replay(
                find=lambda: store.find_decision(decision_id),
                create=create,
                same_content=same_content,
            )

    async def apply(
        self,
        store: DecisionStore,
        organization_id: UUID,
        match_id: UUID,
        request: DecisionRequest,
        *,
        actor: UUID,
        roles: frozenset[str],
        decision_id: UUID | None = None,
        now: datetime | None = None,
    ) -> StoredDecision:
        """Checks and records one decision; the caller holds the organization lock."""
        state = await store.match_state(match_id)
        if state is None:
            raise NotFoundError
        check_decision(state, request, actor, roles)
        decision = StoredDecision(
            decision_id or uuid7(),
            match_id,
            request.action,
            _text(request.reason),
            request.difference_reason,
            _text(request.difference_note),
            actor,
            now or self._clock.now(),
        )
        await store.insert_decision(organization_id, decision)
        await store.audit.record(
            AuditEvent(
                id=uuid7(),
                organization_id=organization_id,
                actor_user_id=actor,
                action=AUDIT_ACTIONS[request.action],
                entity="match",
                entity_id=match_id,
                at=decision.decided_at,
            )
        )
        return decision
