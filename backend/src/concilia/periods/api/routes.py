from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from concilia.periods.application.closing import (
    AccountNotFoundError,
    PeriodAction,
    PeriodError,
    PeriodEvent,
    PeriodService,
)
from concilia.shared.infrastructure.web import current_principal
from concilia.shared.kernel.ids import ClientIdError, IdConflictError
from concilia.shared.kernel.principal import Principal

CurrentPrincipal = Annotated[Principal, Depends(current_principal)]
STATUS_CODES = {
    "role_required": status.HTTP_403_FORBIDDEN,
    "invalid_period": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "future_period": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "reason_required": status.HTTP_422_UNPROCESSABLE_CONTENT,
}


class PeriodEventRequest(BaseModel):
    id: UUID
    bank_account_id: UUID
    period: date
    action: Literal["close", "reopen"]
    reason: str | None = Field(default=None, max_length=500)


class PeriodEventView(BaseModel):
    id: UUID
    bank_account_id: UUID
    period: date
    action: Literal["close", "reopen"]
    reason: str | None
    decided_at: datetime


def _view(event: PeriodEvent) -> PeriodEventView:
    return PeriodEventView(
        id=event.id,
        bank_account_id=event.bank_account_id,
        period=event.period,
        action=event.action.value,
        reason=event.reason,
        decided_at=event.decided_at,
    )


def periods_router(service: PeriodService) -> APIRouter:
    router = APIRouter(prefix="/api/app/period-events", tags=["periods"])

    @router.post("", status_code=status.HTTP_201_CREATED)
    async def decide_period(
        body: PeriodEventRequest, principal: CurrentPrincipal, response: Response
    ) -> PeriodEventView:
        """Close or reopen the month of an account (`period` is its first day); reviewers only.

        Closing needs an open month, not later than the current one, with no proposed or
        confirmed match; reopening needs a closed month and a reason. Idempotent on the
        client-generated id. Errors: 403 `role_required`; 404 `not_found`; 409 `already_closed`,
        `not_closed` or `pending_matches`; 422 `invalid_period`, `future_period` or
        `reason_required`.
        """
        try:
            event, created = await service.decide(
                principal,
                body.id,
                body.bank_account_id,
                body.period,
                PeriodAction(body.action),
                body.reason,
            )
        except PeriodError as error:
            code = STATUS_CODES.get(error.code, status.HTTP_409_CONFLICT)
            raise HTTPException(code, error.code) from None
        except AccountNotFoundError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found") from None
        except ClientIdError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, error.code) from None
        except IdConflictError:
            raise HTTPException(status.HTTP_409_CONFLICT, "id_conflict") from None
        if not created:
            response.status_code = status.HTTP_200_OK
        return _view(event)

    return router
