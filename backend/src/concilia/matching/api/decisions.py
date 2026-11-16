from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from concilia.matching.application.decisions import (
    Action,
    DecisionError,
    DecisionRequest,
    DifferenceReason,
    MatchDecisionService,
    StoredDecision,
)
from concilia.matching.application.runs import (
    InvalidPeriodError,
    NotAllowedError,
    NotFoundError,
)
from concilia.shared.infrastructure.web import current_principal
from concilia.shared.kernel.ids import ClientIdError, IdConflictError
from concilia.shared.kernel.principal import Principal

CurrentPrincipal = Annotated[Principal, Depends(current_principal)]
ActionName = Literal["confirm", "discard", "approve", "reject", "revert"]
ReasonName = Literal["commission", "detraction", "rounding", "overpayment", "other"]
STATUS_CODES = {
    "role_required": status.HTTP_403_FORBIDDEN,
    "reason_required": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "difference_reason": status.HTTP_422_UNPROCESSABLE_CONTENT,
}


class DecisionRequestBody(BaseModel):
    id: UUID
    action: ActionName
    reason: str | None = Field(default=None, max_length=500)
    difference_reason: ReasonName | None = None
    difference_note: str | None = Field(default=None, max_length=500)


class RecordedDecisionView(BaseModel):
    id: UUID
    match_id: UUID
    action: ActionName
    reason: str | None
    difference_reason: ReasonName | None
    difference_note: str | None
    decided_at: datetime


def _view(decision: StoredDecision) -> RecordedDecisionView:
    return RecordedDecisionView(
        id=decision.id,
        match_id=decision.match_id,
        action=decision.action.value,
        reason=decision.reason,
        difference_reason=(
            decision.difference_reason.value if decision.difference_reason else None
        ),
        difference_note=decision.difference_note,
        decided_at=decision.decided_at,
    )


class BatchRequestBody(BaseModel):
    action: Literal["confirm", "approve"]
    bank_account_id: UUID
    period: date


class BatchView(BaseModel):
    decided: int
    skipped: int


def decisions_router(service: MatchDecisionService) -> APIRouter:
    router = APIRouter(prefix="/api/app/matches", tags=["inbox"])

    @router.post("/batch")
    async def decide_batch(body: BatchRequestBody, principal: CurrentPrincipal) -> BatchView:
        """Confirm (analysts) every proposal, or approve (reviewers) every confirmed match,
        scored 100 in one account and month (`period` is its first day). Approvals the reviewer
        may not give under four eyes are counted in `skipped` for someone else. Repeating it
        decides nothing new.
        """
        try:
            result = await service.decide_batch(
                principal, body.bank_account_id, body.period, Action(body.action)
            )
        except DecisionError as error:
            code = STATUS_CODES.get(error.code, status.HTTP_409_CONFLICT)
            raise HTTPException(code, error.code) from None
        except NotAllowedError:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "role_required") from None
        except InvalidPeriodError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_period") from None
        return BatchView(decided=result.decided, skipped=result.skipped)

    @router.post("/{match_id}/decisions", status_code=status.HTTP_201_CREATED)
    async def decide_match(
        match_id: UUID,
        body: DecisionRequestBody,
        principal: CurrentPrincipal,
        response: Response,
    ) -> RecordedDecisionView:
        """Record a decision following the state table: an analyst confirms or discards a
        proposal, and a reviewer other than whoever created or confirmed it approves, rejects or
        reverts it.

        Idempotent on the client-generated id. Errors: 403 `role_required`; 409 `wrong_state`,
        `four_eyes` or `closed_period`; 422 `reason_required` (reject and revert) or
        `difference_reason` (a confirmed difference needs a reason, `overpayment` only when
        positive and `other` with a note).
        """
        request = DecisionRequest(
            Action(body.action),
            body.reason,
            DifferenceReason(body.difference_reason) if body.difference_reason else None,
            body.difference_note,
        )
        try:
            decision, created = await service.decide(principal, match_id, body.id, request)
        except DecisionError as error:
            code = STATUS_CODES.get(error.code, status.HTTP_409_CONFLICT)
            raise HTTPException(code, error.code) from None
        except NotAllowedError:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "role_required") from None
        except NotFoundError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found") from None
        except ClientIdError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, error.code) from None
        except IdConflictError:
            raise HTTPException(status.HTTP_409_CONFLICT, "id_conflict") from None
        if not created:
            response.status_code = status.HTTP_200_OK
        return _view(decision)

    return router
