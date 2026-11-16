from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID, uuid7

from concilia.ai.application.llm import LlmClient, LlmError
from concilia.ai.application.prompts import PROMPT_VERSION, system_prompt, user_input
from concilia.ai.application.response import RESPONSE_SCHEMA, parse_output, proposals
from concilia.ai.domain.suggestions import (
    Candidate,
    CreditFacts,
    OpenReceivable,
    ServerSuggestion,
    choose_candidates,
    recompute_all,
)
from concilia.audit.application.recorder import AuditAction, AuditEvent, AuditRecorder
from concilia.shared.kernel.clock import Clock, lima_day_start
from concilia.shared.kernel.ids import create_or_replay, validate_client_id
from concilia.shared.kernel.principal import Principal

__all__ = [
    "AiError",
    "DecisionAction",
    "FoundSuggestion",
    "LlmChooser",
    "LlmError",
    "ReceivableLabel",
    "StoredSuggestion",
    "SuggestionDecision",
    "SuggestionRequest",
    "SuggestionService",
    "SuggestionStore",
    "SuggestionTransactions",
    "Usage",
]

ORGANIZATION_DAILY_LIMIT = 50
KIND = "ai_suggest"

type JobStatus = Literal["queued", "running", "done", "failed"]


type DecisionAction = Literal["accept", "reject"]


@dataclass(frozen=True)
class SuggestionDecision:
    id: UUID
    ai_suggestion_id: UUID
    suggestion_index: int
    action: DecisionAction
    reason: str | None
    match_id: UUID | None
    decided_by: UUID
    decided_at: datetime


class AiError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SuggestionRequest:
    """The `ai_suggest` job; its id is the client's id for the request."""

    id: UUID
    bank_movement_id: UUID
    requested_by: UUID | None
    status: JobStatus
    error_code: str | None


@dataclass(frozen=True)
class StoredSuggestion:
    id: UUID
    job_id: UUID
    bank_movement_id: UUID
    model: str
    prompt_version: int
    candidates: dict[str, UUID]
    response: object
    server_applied: list[ServerSuggestion] | None
    no_match_reason: str | None
    replayed: bool
    input_tokens: int
    output_tokens: int
    created_by: UUID
    created_at: datetime

    @property
    def valid(self) -> bool:
        return self.server_applied is not None


@dataclass(frozen=True)
class ReceivableLabel:
    doc_number: str
    customer_name: str


@dataclass(frozen=True)
class FoundSuggestion:
    request: SuggestionRequest
    suggestion: StoredSuggestion | None
    labels: dict[UUID, ReceivableLabel]
    decisions: list[SuggestionDecision]


@dataclass(frozen=True)
class Usage:
    available: bool
    used_today: int
    daily_limit: int | None


class LlmChooser(Protocol):
    def for_organization(self, is_demo: bool) -> LlmClient | None: ...


class SuggestionStore(Protocol):
    audit: AuditRecorder

    async def lock_organization(self, organization_id: UUID) -> None: ...

    async def lock_global_quota(self) -> None: ...

    async def is_demo(self, organization_id: UUID) -> bool: ...

    async def free_credit(self, bank_movement_id: UUID) -> CreditFacts | None:
        """A live credit in no active match whose month is open, or None."""
        ...

    async def open_receivables(self) -> Sequence[OpenReceivable]: ...

    async def organization_usage(self, since: datetime, until: datetime) -> int: ...

    async def global_usage(self, since: datetime, until: datetime) -> int: ...

    async def find_request(self, request_id: UUID) -> SuggestionRequest | None: ...

    async def enqueue(
        self, organization_id: UUID, request: SuggestionRequest, requested_by: UUID, now: datetime
    ) -> None: ...

    async def find_suggestion(self, job_id: UUID) -> StoredSuggestion | None: ...

    async def receivable_labels(self, ids: Sequence[UUID]) -> dict[UUID, ReceivableLabel]: ...

    async def decisions_of(self, ai_suggestion_id: UUID) -> list[SuggestionDecision]: ...

    async def insert_suggestion(
        self, organization_id: UUID, suggestion: StoredSuggestion
    ) -> None: ...


class SuggestionTransactions(Protocol):
    def organization(
        self, organization_id: UUID
    ) -> AbstractAsyncContextManager[SuggestionStore]: ...


def _analyst_organization(principal: Principal) -> UUID:
    if principal.organization_id is None or "analyst" not in principal.roles:
        raise AiError("role_required")
    return principal.organization_id


def _member_organization(principal: Principal) -> UUID:
    if principal.organization_id is None or not principal.roles:
        raise AiError("role_required")
    return principal.organization_id


class SuggestionService:
    def __init__(
        self,
        transactions: SuggestionTransactions,
        llm: LlmChooser,
        clock: Clock,
        *,
        global_daily_limit: int = 200,
    ) -> None:
        self._transactions = transactions
        self._llm = llm
        self._clock = clock
        self._global_daily_limit = global_daily_limit

    async def request(
        self, principal: Principal, request_id: UUID, bank_movement_id: UUID
    ) -> tuple[SuggestionRequest, bool]:
        """Queue a suggestion for one free credit. Jobs are counted when queued, under the
        organization lock and a global lock, so a burst cannot exceed the daily limits."""
        organization_id = _analyst_organization(principal)
        now = self._clock.now()
        validate_client_id(request_id, now)
        today = self._clock.today_lima()
        since, until = lima_day_start(today), lima_day_start(today + timedelta(days=1))
        async with self._transactions.organization(organization_id) as store:
            await store.lock_organization(organization_id)
            await store.lock_global_quota()

            async def create() -> SuggestionRequest:
                if await store.free_credit(bank_movement_id) is None:
                    raise AiError("credit_not_free")
                if not await store.is_demo(organization_id):
                    if self._llm.for_organization(is_demo=False) is None:
                        raise AiError("ai_unavailable")
                    if await store.organization_usage(since, until) >= ORGANIZATION_DAILY_LIMIT:
                        raise AiError("ai_daily_limit")
                    if await store.global_usage(since, until) >= self._global_daily_limit:
                        raise AiError("ai_global_limit")
                request = SuggestionRequest(
                    request_id, bank_movement_id, principal.user_id, "queued", None
                )
                await store.enqueue(organization_id, request, principal.user_id, now)
                await store.audit.record(
                    AuditEvent(
                        id=uuid7(),
                        organization_id=organization_id,
                        actor_user_id=principal.user_id,
                        action=AuditAction.AI_SUGGESTION_REQUESTED,
                        entity="ai_suggestion",
                        entity_id=request_id,
                        at=now,
                    )
                )
                return request

            def same_content(existing: SuggestionRequest) -> bool:
                return (existing.bank_movement_id, existing.requested_by) == (
                    bank_movement_id,
                    principal.user_id,
                )

            return await create_or_replay(
                find=lambda: store.find_request(request_id),
                create=create,
                same_content=same_content,
            )

    async def usage(self, principal: Principal) -> Usage:
        """Whether the organization can ask the AI and how many requests it made today (Lima);
        demo organizations have no daily limit."""
        organization_id = _member_organization(principal)
        today = self._clock.today_lima()
        since, until = lima_day_start(today), lima_day_start(today + timedelta(days=1))
        async with self._transactions.organization(organization_id) as store:
            is_demo = await store.is_demo(organization_id)
            return Usage(
                available=self._llm.for_organization(is_demo=is_demo) is not None,
                used_today=await store.organization_usage(since, until),
                daily_limit=None if is_demo else ORGANIZATION_DAILY_LIMIT,
            )

    async def find(self, principal: Principal, request_id: UUID) -> FoundSuggestion:
        organization_id = _member_organization(principal)
        async with self._transactions.organization(organization_id) as store:
            request = await store.find_request(request_id)
            if request is None:
                raise AiError("not_found")
            suggestion = await store.find_suggestion(request_id)
            shown = suggestion.server_applied if suggestion and suggestion.server_applied else []
            ids = [item.receivable_id for server in shown for item in server.applied]
            return FoundSuggestion(
                request,
                suggestion,
                await store.receivable_labels(ids),
                await store.decisions_of(suggestion.id) if suggestion else [],
            )

    async def suggest(
        self, organization_id: UUID, job_id: UUID, store: SuggestionStore, requested_by: UUID
    ) -> None:
        """Runs in the `ai_suggest` job. A rerun after the suggestion was stored does nothing;
        a failed call stores nothing and leaves its code on the job."""
        if await store.find_suggestion(job_id) is not None:
            return
        request = await store.find_request(job_id)
        if request is None:
            raise AiError("not_found")
        credit = await store.free_credit(request.bank_movement_id)
        if credit is None:
            raise AiError("credit_not_free")
        candidates = choose_candidates(credit, await store.open_receivables())
        if not candidates:
            raise AiError("no_candidates")
        is_demo = await store.is_demo(organization_id)
        client = self._llm.for_organization(is_demo=is_demo)
        if client is None:
            raise AiError("ai_unavailable")
        result = await client.complete(
            system=system_prompt(PROMPT_VERSION),
            user=user_input(credit, candidates),
            schema=RESPONSE_SCHEMA,
        )
        output = parse_output(result.output)
        await store.insert_suggestion(
            organization_id,
            StoredSuggestion(
                id=uuid7(),
                job_id=job_id,
                bank_movement_id=credit.id,
                model=result.model,
                prompt_version=PROMPT_VERSION,
                candidates=_aliases(candidates),
                response=output.model_dump(mode="json") if output else result.output,
                server_applied=(
                    recompute_all(credit.amount_cents, proposals(output), candidates)
                    if output
                    else None
                ),
                no_match_reason=output.no_match_reason if output else None,
                replayed=is_demo,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                created_by=requested_by,
                created_at=self._clock.now(),
            ),
        )


def _aliases(candidates: Sequence[Candidate]) -> dict[str, UUID]:
    return {candidate.alias: candidate.receivable.id for candidate in candidates}
