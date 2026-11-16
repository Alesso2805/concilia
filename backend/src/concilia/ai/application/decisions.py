from contextlib import AbstractAsyncContextManager
from typing import Protocol
from uuid import UUID, uuid7

from concilia.ai.application.service import (
    AiError,
    DecisionAction,
    SuggestionDecision,
    SuggestionStore,
)
from concilia.audit.application.recorder import AuditAction, AuditEvent
from concilia.matching.application.decisions import DecisionError, DifferenceReason
from concilia.matching.application.manual import (
    AiOrigin,
    ManualApplication,
    ManualMatch,
    ManualMatchService,
    ManualStore,
    StoredManualMatch,
)
from concilia.matching.application.runs import NotFoundError as MatchNotFoundError
from concilia.shared.kernel.clock import Clock
from concilia.shared.kernel.ids import create_or_replay, validate_client_id
from concilia.shared.kernel.principal import Principal

__all__ = [
    "DecisionStore",
    "DecisionTransactions",
    "SuggestionDecision",
    "SuggestionDecisionService",
]

MAX_REASON = 500


class DecisionStore(SuggestionStore, Protocol):
    matches: ManualStore

    async def credit_account(self, bank_movement_id: UUID) -> UUID: ...

    async def find_decision(self, decision_id: UUID) -> SuggestionDecision | None: ...

    async def insert_decision(
        self, organization_id: UUID, decision: SuggestionDecision
    ) -> None: ...


class DecisionTransactions(Protocol):
    def organization(self, organization_id: UUID) -> AbstractAsyncContextManager[DecisionStore]: ...


def _reason(value: str | None) -> str | None:
    stripped = (value or "").strip()
    return stripped or None


class SuggestionDecisionService:
    def __init__(
        self, transactions: DecisionTransactions, manual: ManualMatchService, clock: Clock
    ) -> None:
        self._transactions = transactions
        self._manual = manual
        self._clock = clock

    async def decide(
        self,
        principal: Principal,
        request_id: UUID,
        decision_id: UUID,
        index: int,
        action: DecisionAction,
        reason: str | None,
    ) -> tuple[SuggestionDecision, bool]:
        """An analyst accepts one suggestion, which creates a proposed match with source `ai`
        that follows the normal flow, or rejects it with a reason. The AI never decides."""
        organization_id = principal.organization_id
        if organization_id is None or "analyst" not in principal.roles:
            raise AiError("role_required")
        now = self._clock.now()
        validate_client_id(decision_id, now)
        reason = _reason(reason)
        if action == "reject" and reason is None:
            raise AiError("reason_required")
        if reason is not None and len(reason) > MAX_REASON:
            raise AiError("reason_too_long")
        async with self._transactions.organization(organization_id) as store:
            await store.lock_organization(organization_id)
            suggestion = await store.find_suggestion(request_id)
            if suggestion is None:
                raise AiError("not_found")

            async def create() -> SuggestionDecision:
                shown = suggestion.server_applied
                if shown is None:
                    raise AiError("invalid_suggestion")
                if not 0 <= index < len(shown):
                    raise AiError("not_found")
                if any(
                    d.suggestion_index == index for d in await store.decisions_of(suggestion.id)
                ):
                    raise AiError("already_decided")
                match_id = None
                if action == "accept":
                    chosen = shown[index]
                    if await store.free_credit(suggestion.bank_movement_id) is None:
                        raise AiError("credit_not_free")
                    stored = StoredManualMatch(
                        uuid7(),
                        await store.credit_account(suggestion.bank_movement_id),
                        principal.user_id,
                        ManualMatch(
                            (suggestion.bank_movement_id,),
                            tuple(
                                ManualApplication(item.receivable_id, item.applied_cents)
                                for item in chosen.applied
                            ),
                        ),
                    )
                    origin = AiOrigin(
                        suggestion.id,
                        chosen.explanation,
                        DifferenceReason(chosen.difference_reason)
                        if chosen.difference_reason
                        else None,
                    )
                    try:
                        await self._manual.propose_from_ai(
                            store.matches, organization_id, stored, origin, now
                        )
                    except DecisionError as error:
                        raise AiError(error.code) from None
                    except MatchNotFoundError:
                        raise AiError("not_found") from None
                    match_id = stored.id
                decision = SuggestionDecision(
                    decision_id,
                    suggestion.id,
                    index,
                    action,
                    reason,
                    match_id,
                    principal.user_id,
                    now,
                )
                await store.insert_decision(organization_id, decision)
                await store.audit.record(
                    AuditEvent(
                        id=uuid7(),
                        organization_id=organization_id,
                        actor_user_id=principal.user_id,
                        action=(
                            AuditAction.AI_SUGGESTION_ACCEPTED
                            if action == "accept"
                            else AuditAction.AI_SUGGESTION_REJECTED
                        ),
                        entity="ai_suggestion",
                        entity_id=request_id,
                        at=now,
                    )
                )
                return decision

            def same_content(existing: SuggestionDecision) -> bool:
                return (
                    existing.ai_suggestion_id,
                    existing.suggestion_index,
                    existing.action,
                    existing.reason,
                    existing.decided_by,
                ) == (suggestion.id, index, action, reason, principal.user_id)

            return await create_or_replay(
                find=lambda: store.find_decision(decision_id),
                create=create,
                same_content=same_content,
            )
