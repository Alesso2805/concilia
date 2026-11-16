from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from concilia.matching.application.decisions import DifferenceReason
from concilia.reporting.application.dashboard import (
    AgeBucket,
    CreditStatus,
    DashboardService,
    InvalidPeriodError,
    NotAllowedError,
    NotFoundError,
    Tally,
)
from concilia.shared.infrastructure.web import current_principal
from concilia.shared.kernel.principal import Principal

CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


class TallyView(BaseModel):
    count: int
    cents: int


class CreditTotalsView(BaseModel):
    free: TallyView
    proposed: TallyView
    confirmed: TallyView
    approved: TallyView


class AgeView(BaseModel):
    bucket: AgeBucket
    count: int
    cents: int


class DifferenceView(BaseModel):
    reason: DifferenceReason
    count: int
    cents: int


class DashboardView(BaseModel):
    period: date
    reference_date: date
    closed: bool
    credits: CreditTotalsView
    pending: list[AgeView]
    differences: list[DifferenceView]


def _tally(tally: Tally) -> TallyView:
    return TallyView(count=tally.count, cents=tally.cents)


def reports_router(service: DashboardService) -> APIRouter:
    router = APIRouter(prefix="/api/app/reports", tags=["reports"])

    @router.get("/dashboard")
    async def get_dashboard(
        principal: CurrentPrincipal, bank_account_id: UUID, period: date
    ) -> DashboardView:
        """The state of one account and month (`period` is its first day), for every role.

        `credits`: the month's credits by status (reconciled means approved). `pending`: credits
        not yet approved, of this and earlier months, booked up to `reference_date` (the last
        day of the month, or today in the current month), by days before it. `differences`:
        confirmed or approved matches of the month with a difference, by reason; `cents` is
        credits minus applied. 403 `role_required`; 404 `not_found`; 422 `invalid_period`.
        """
        try:
            dashboard = await service.dashboard(principal, bank_account_id, period)
        except NotAllowedError:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "role_required") from None
        except NotFoundError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found") from None
        except InvalidPeriodError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_period") from None
        credits = dashboard.credits
        return DashboardView(
            period=dashboard.period,
            reference_date=dashboard.reference_date,
            closed=dashboard.closed,
            credits=CreditTotalsView(
                free=_tally(credits[CreditStatus.FREE]),
                proposed=_tally(credits[CreditStatus.PROPOSED]),
                confirmed=_tally(credits[CreditStatus.CONFIRMED]),
                approved=_tally(credits[CreditStatus.APPROVED]),
            ),
            pending=[
                AgeView(bucket=bucket, count=tally.count, cents=tally.cents)
                for bucket, tally in dashboard.pending.items()
            ],
            differences=[
                DifferenceView(
                    reason=DifferenceReason(item.reason), count=item.count, cents=item.cents
                )
                for item in dashboard.differences
            ],
        )

    return router
