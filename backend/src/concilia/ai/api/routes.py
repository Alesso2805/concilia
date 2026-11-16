from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from concilia.ai.application.decisions import SuggestionDecisionService
from concilia.ai.application.service import (
    AiError,
    FoundSuggestion,
    ReceivableLabel,
    SuggestionDecision,
    SuggestionRequest,
    SuggestionService,
)
from concilia.ai.domain.suggestions import ServerSuggestion
from concilia.shared.infrastructure.web import current_principal
from concilia.shared.kernel.ids import ClientIdError, IdConflictError
from concilia.shared.kernel.principal import Principal

CurrentPrincipal = Annotated[Principal, Depends(current_principal)]
STATUS_CODES = {
    "role_required": status.HTTP_403_FORBIDDEN,
    "not_found": status.HTTP_404_NOT_FOUND,
    "reason_required": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "reason_too_long": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "ai_daily_limit": status.HTTP_429_TOO_MANY_REQUESTS,
    "ai_global_limit": status.HTTP_429_TOO_MANY_REQUESTS,
}


class SuggestionRequestBody(BaseModel):
    id: UUID
    bank_movement_id: UUID


class SuggestedReceivableView(BaseModel):
    alias: str
    receivable_id: UUID
    doc_number: str
    customer_name: str
    applied_cents: int


class DecisionView(BaseModel):
    id: UUID
    index: int
    action: Literal["accept", "reject"]
    reason: str | None
    match_id: UUID | None
    decided_at: datetime


class DecisionRequestBody(BaseModel):
    id: UUID
    index: int = Field(ge=0, le=2)
    action: Literal["accept", "reject"]
    reason: str | None = Field(default=None, max_length=500)


class UsageView(BaseModel):
    available: bool
    used_today: int
    daily_limit: int | None


class SuggestionItemView(BaseModel):
    index: int
    decision: DecisionView | None
    receivables: list[SuggestedReceivableView]
    difference_cents: int
    difference_reason: (
        Literal["commission", "detraction", "rounding", "overpayment", "other"] | None
    )
    confidence: Literal["low", "medium", "high"]
    explanation: str
    recomputed: bool


class SuggestionView(BaseModel):
    id: UUID
    job_id: UUID
    bank_movement_id: UUID
    status: Literal["queued", "running", "done", "failed"]
    error_code: str | None
    valid: bool | None
    suggestions: list[SuggestionItemView]
    no_match_reason: str | None


def _decision(decision: SuggestionDecision) -> DecisionView:
    return DecisionView(
        id=decision.id,
        index=decision.suggestion_index,
        action=decision.action,
        reason=decision.reason,
        match_id=decision.match_id,
        decided_at=decision.decided_at,
    )


def _item(
    index: int,
    suggestion: ServerSuggestion,
    labels: dict[UUID, ReceivableLabel],
    decisions: dict[int, SuggestionDecision],
) -> SuggestionItemView:
    decision = decisions.get(index)
    return SuggestionItemView(
        index=index,
        decision=_decision(decision) if decision else None,
        receivables=[
            SuggestedReceivableView(
                alias=item.alias,
                receivable_id=item.receivable_id,
                doc_number=labels[item.receivable_id].doc_number,
                customer_name=labels[item.receivable_id].customer_name,
                applied_cents=item.applied_cents,
            )
            for item in suggestion.applied
        ],
        difference_cents=suggestion.difference_cents,
        difference_reason=suggestion.difference_reason,
        confidence=suggestion.confidence,
        explanation=suggestion.explanation,
        recomputed=suggestion.recomputed,
    )


def _view(request: SuggestionRequest, found: FoundSuggestion | None = None) -> SuggestionView:
    suggestion = found.suggestion if found else None
    shown = suggestion.server_applied if suggestion and suggestion.server_applied else []
    decisions = {d.suggestion_index: d for d in found.decisions} if found else {}
    labels = found.labels if found else {}
    return SuggestionView(
        id=request.id,
        job_id=request.id,
        bank_movement_id=request.bank_movement_id,
        status=request.status,
        error_code=request.error_code,
        valid=suggestion.valid if suggestion else None,
        suggestions=[_item(i, item, labels, decisions) for i, item in enumerate(shown)],
        no_match_reason=suggestion.no_match_reason if suggestion else None,
    )


def _error(error: AiError) -> HTTPException:
    return HTTPException(STATUS_CODES.get(error.code, status.HTTP_409_CONFLICT), error.code)


def ai_router(service: SuggestionService, decisions: SuggestionDecisionService) -> APIRouter:
    router = APIRouter(prefix="/api/app/ai", tags=["ai"])

    @router.get("/usage")
    async def get_ai_usage(principal: CurrentPrincipal) -> UsageView:
        """Whether this organization can ask the AI now and how many requests it made today
        (Lima day); `daily_limit` is null in demo organizations."""
        try:
            usage = await service.usage(principal)
        except AiError as error:
            raise _error(error) from None
        return UsageView(
            available=usage.available, used_today=usage.used_today, daily_limit=usage.daily_limit
        )

    @router.post("/suggestions", status_code=status.HTTP_201_CREATED)
    async def request_suggestion(
        body: SuggestionRequestBody, principal: CurrentPrincipal, response: Response
    ) -> SuggestionView:
        """Ask the AI for candidates for one free credit (analysts). The client id is also the
        id of the `ai_suggest` job to follow. The AI never decides: its suggestions are
        validated and recomputed by the server and a person accepts or rejects them.
        Idempotent on the client id. 403 `role_required`; 409 `credit_not_free`,
        `ai_unavailable` or `id_conflict`; 422 `id_not_uuid7` or `id_clock_skew`; 429
        `ai_daily_limit` (50 per organization and Lima day) or `ai_global_limit`.
        """
        try:
            request, created = await service.request(principal, body.id, body.bank_movement_id)
        except AiError as error:
            raise _error(error) from None
        except ClientIdError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, error.code) from None
        except IdConflictError:
            raise HTTPException(status.HTTP_409_CONFLICT, "id_conflict") from None
        if not created:
            response.status_code = status.HTTP_200_OK
        return _view(request)

    @router.get("/suggestions/{suggestion_id}")
    async def get_suggestion(suggestion_id: UUID, principal: CurrentPrincipal) -> SuggestionView:
        """The state of a request and, once its job is done, the server's version of each
        suggestion. An output that did not validate has `valid` false and shows nothing.
        404 `not_found`."""
        try:
            found = await service.find(principal, suggestion_id)
        except AiError as error:
            raise _error(error) from None
        return _view(found.request, found)

    @router.post("/suggestions/{suggestion_id}/decisions", status_code=status.HTTP_201_CREATED)
    async def decide_suggestion(
        suggestion_id: UUID,
        body: DecisionRequestBody,
        principal: CurrentPrincipal,
        response: Response,
    ) -> DecisionView:
        """An analyst accepts one suggestion (by its `index`), which creates a proposed match
        with source `ai` for the normal confirm and approve flow, or rejects it with a reason.
        Idempotent on the client id. 403 `role_required`; 404 `not_found`; 409
        `already_decided`, `invalid_suggestion`, `credit_not_free`, `insufficient_balance` or
        `id_conflict`; 422 `reason_required`."""
        try:
            decision, created = await decisions.decide(
                principal, suggestion_id, body.id, body.index, body.action, body.reason
            )
        except AiError as error:
            raise _error(error) from None
        except ClientIdError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, error.code) from None
        except IdConflictError:
            raise HTTPException(status.HTTP_409_CONFLICT, "id_conflict") from None
        if not created:
            response.status_code = status.HTTP_200_OK
        return _decision(decision)

    return router
