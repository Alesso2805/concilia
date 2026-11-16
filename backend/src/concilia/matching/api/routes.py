from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from concilia.matching.application.runs import (
    ClosedPeriodError,
    EngineRunService,
    InvalidPeriodError,
    NotAllowedError,
    NotFoundError,
    RunInProgressError,
    RunRequest,
)
from concilia.matching.domain.runs import EngineRun
from concilia.shared.infrastructure.web import current_principal
from concilia.shared.kernel.ids import ClientIdError, IdConflictError
from concilia.shared.kernel.principal import Principal

CurrentPrincipal = Annotated[Principal, Depends(current_principal)]

ERRORS: dict[type[Exception], tuple[int, str]] = {
    NotAllowedError: (status.HTTP_403_FORBIDDEN, "role_required"),
    NotFoundError: (status.HTTP_404_NOT_FOUND, "not_found"),
    InvalidPeriodError: (status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_period"),
    ClosedPeriodError: (status.HTTP_409_CONFLICT, "closed_period"),
    RunInProgressError: (status.HTTP_409_CONFLICT, "run_in_progress"),
    IdConflictError: (status.HTTP_409_CONFLICT, "id_conflict"),
}
HANDLED: tuple[type[Exception], ...] = (ClientIdError, *ERRORS)


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, ClientIdError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, error.code)
    code, detail = ERRORS[type(error)]
    return HTTPException(code, detail)


class EngineRunRequest(BaseModel):
    id: UUID
    bank_account_id: UUID
    period: date


class EngineRunView(BaseModel):
    id: UUID
    bank_account_id: UUID
    period: date
    job_id: UUID | None
    rules_version: int
    proposals_count: int | None
    started_at: datetime
    finished_at: datetime | None


def _view(run: EngineRun) -> EngineRunView:
    return EngineRunView(
        id=run.id,
        bank_account_id=run.bank_account_id,
        period=run.period,
        job_id=run.job_id,
        rules_version=run.rules_version,
        proposals_count=run.proposals_count,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


def engine_runs_router(service: EngineRunService) -> APIRouter:
    router = APIRouter(prefix="/api/app/engine-runs", tags=["matching"])

    @router.post("", status_code=status.HTTP_201_CREATED)
    async def request_engine_run(
        body: EngineRunRequest, principal: CurrentPrincipal, response: Response
    ) -> EngineRunView:
        """Queue the matching engine over the free credits of one account and month.

        Analysts only; `period` is the first day of the month. Idempotent on the
        client-generated id. 409 `closed_period` for a closed month and `run_in_progress` while
        another run of the same account and month is queued or running.
        """
        request = RunRequest(body.id, body.bank_account_id, body.period)
        try:
            run, created = await service.request(principal, request)
        except HANDLED as error:
            raise _http_error(error) from None
        if not created:
            response.status_code = status.HTTP_200_OK
        return _view(run)

    @router.get("/{run_id}")
    async def get_engine_run(run_id: UUID, principal: CurrentPrincipal) -> EngineRunView:
        """An engine run; `finished_at` and `proposals_count` are set when it ends."""
        try:
            return _view(await service.find(principal, run_id))
        except HANDLED as error:
            raise _http_error(error) from None

    return router
