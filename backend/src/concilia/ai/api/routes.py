from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from concilia.ai.application.service import (
    AiError,
    ReceivableLabel,
    StoredSuggestion,
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


class SuggestionItemView(BaseModel):
    index: int
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


def _item(
    index: int, suggestion: ServerSuggestion, labels: dict[UUID, ReceivableLabel]
) -> SuggestionItemView:
    return SuggestionItemView(
        index=index,
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


def _view(
    request: SuggestionRequest,
    suggestion: StoredSuggestion | None = None,
    labels: dict[UUID, ReceivableLabel] | None = None,
) -> SuggestionView:
    shown = suggestion.server_applied if suggestion and suggestion.server_applied else []
    return SuggestionView(
        id=request.id,
        job_id=request.id,
        bank_movement_id=request.bank_movement_id,
        status=request.status,
        error_code=request.error_code,
        valid=suggestion.valid if suggestion else None,
        suggestions=[_item(index, item, labels or {}) for index, item in enumerate(shown)],
        no_match_reason=suggestion.no_match_reason if suggestion else None,
    )


def _error(error: AiError) -> HTTPException:
    return HTTPException(STATUS_CODES.get(error.code, status.HTTP_409_CONFLICT), error.code)


def ai_router(service: SuggestionService) -> APIRouter:
    router = APIRouter(prefix="/api/app/ai/suggestions", tags=["ai"])

    @router.post("", status_code=status.HTTP_201_CREATED)
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

    @router.get("/{suggestion_id}")
    async def get_suggestion(suggestion_id: UUID, principal: CurrentPrincipal) -> SuggestionView:
        """The state of a request and, once its job is done, the server's version of each
        suggestion. An output that did not validate has `valid` false and shows nothing.
        404 `not_found`."""
        try:
            request, suggestion, labels = await service.find(principal, suggestion_id)
        except AiError as error:
            raise _error(error) from None
        return _view(request, suggestion, labels)

    return router
