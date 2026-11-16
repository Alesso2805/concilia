from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from concilia.matching.api.routes import HANDLED, http_error
from concilia.matching.application.inbox import InboxService
from concilia.matching.domain.inbox import (
    CreditRow,
    MatchDetail,
    MatchFilters,
    MatchRow,
    MatchStatus,
)
from concilia.shared.infrastructure.web import current_principal
from concilia.shared.kernel.cursor import InvalidCursorError, decode_date_cursor, encode_cursor
from concilia.shared.kernel.principal import Principal

CurrentPrincipal = Annotated[Principal, Depends(current_principal)]
Account = Annotated[UUID, Query()]
Period = Annotated[date, Query(description="First day of the month")]
Limit = Annotated[int, Query(gt=0, le=100)]
Cents = Annotated[int | None, Query(ge=0)]
Rule = Literal["R1", "R2", "R3", "R4", "R5", "R6"]
Reason = Literal["commission", "detraction", "rounding", "overpayment", "other"]
Status = Literal["proposed", "confirmed", "approved", "discarded", "rejected", "reverted"]


class PeriodView(BaseModel):
    period: date
    closed: bool
    credits: int


class CountsView(BaseModel):
    free: int
    proposed: int
    confirmed: int
    approved: int


class CreditView(BaseModel):
    id: UUID
    booked_on: date
    description: str
    operation_number: str | None
    amount_cents: int


class CreditPageView(BaseModel):
    credits: list[CreditView]
    has_previous: bool
    has_next: bool
    previous_cursor: str | None
    next_cursor: str | None


class MatchRowView(BaseModel):
    id: UUID
    source: Literal["engine", "ai", "manual"]
    rule: Rule | None
    score: int | None
    status: Status
    booked_on: date
    description: str
    documents: list[str]
    customers: list[str]
    credits_cents: int
    applied_cents: int
    difference_cents: int


class MatchPageView(BaseModel):
    matches: list[MatchRowView]
    has_previous: bool
    has_next: bool
    previous_cursor: str | None
    next_cursor: str | None


class OpenReceivableView(BaseModel):
    id: UUID
    doc_number: str
    customer_name: str
    customer_tax_id: str | None
    issued_on: date
    due_on: date
    amount_cents: int
    available_cents: int


class OpenReceivablePageView(BaseModel):
    receivables: list[OpenReceivableView]
    has_previous: bool
    has_next: bool
    previous_cursor: str | None
    next_cursor: str | None


class MatchedReceivableView(BaseModel):
    id: UUID
    doc_number: str
    customer_name: str
    due_on: date
    amount_cents: int
    applied_cents: int
    available_cents: int


class DecisionView(BaseModel):
    action: Literal["confirm", "discard", "approve", "reject", "revert"]
    reason: str | None
    difference_reason: Reason | None
    difference_note: str | None
    decided_by: str
    decided_at: datetime


class MatchDetailView(BaseModel):
    id: UUID
    bank_account_id: UUID
    source: Literal["engine", "ai", "manual"]
    rule: Rule | None
    score: int | None
    status: Status
    suggested_difference_reason: Reason | None
    explanation: str | None
    created_at: datetime
    credits: list[CreditView]
    receivables: list[MatchedReceivableView]
    decisions: list[DecisionView]
    credits_cents: int
    applied_cents: int
    difference_cents: int


def _credit(credit: CreditRow) -> CreditView:
    return CreditView(
        id=credit.id,
        booked_on=credit.booked_on,
        description=credit.description,
        operation_number=credit.operation_number,
        amount_cents=credit.amount_cents,
    )


def _match_row(match: MatchRow) -> MatchRowView:
    return MatchRowView(
        id=match.id,
        source=match.source,
        rule=match.rule,
        score=match.score,
        status=match.status.value,
        booked_on=match.booked_on,
        description=match.description,
        documents=list(match.documents),
        customers=list(match.customers),
        credits_cents=match.credits_cents,
        applied_cents=match.applied_cents,
        difference_cents=match.difference_cents,
    )


def _detail(detail: MatchDetail) -> MatchDetailView:
    credits = sum(credit.amount_cents for credit in detail.credits)
    return MatchDetailView(
        id=detail.id,
        bank_account_id=detail.bank_account_id,
        source=detail.source,
        rule=detail.rule,
        score=detail.score,
        status=detail.status.value,
        suggested_difference_reason=detail.suggested_difference_reason,
        explanation=detail.explanation,
        created_at=detail.created_at,
        credits=[_credit(credit) for credit in detail.credits],
        receivables=[
            MatchedReceivableView(
                id=item.id,
                doc_number=item.doc_number,
                customer_name=item.customer_name,
                due_on=item.due_on,
                amount_cents=item.amount_cents,
                applied_cents=item.applied_cents,
                available_cents=item.available_cents,
            )
            for item in detail.receivables
        ],
        decisions=[
            DecisionView(
                action=decision.action,
                reason=decision.reason,
                difference_reason=decision.difference_reason,
                difference_note=decision.difference_note,
                decided_by=decision.decided_by,
                decided_at=decision.decided_at,
            )
            for decision in detail.decisions
        ],
        credits_cents=credits,
        applied_cents=credits - detail.difference_cents,
        difference_cents=detail.difference_cents,
    )


def _invalid_cursor() -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_cursor")


def _match_cursor(cursor: str | None) -> UUID | None:
    if cursor is None:
        return None
    try:
        return UUID(cursor)
    except ValueError:
        raise _invalid_cursor() from None


def inbox_router(service: InboxService) -> APIRouter:
    router = APIRouter(prefix="/api/app", tags=["inbox"])

    @router.get("/inbox/periods")
    async def list_inbox_periods(
        bank_account_id: Account, principal: CurrentPrincipal
    ) -> list[PeriodView]:
        """The months with live credits in an account, newest first, and whether each is closed."""
        try:
            periods = await service.periods(principal, bank_account_id)
        except HANDLED as error:
            raise http_error(error) from None
        return [PeriodView(period=p.period, closed=p.closed, credits=p.credits) for p in periods]

    @router.get("/inbox/counts")
    async def get_inbox_counts(
        bank_account_id: Account, period: Period, principal: CurrentPrincipal
    ) -> CountsView:
        """How many free credits and proposed, confirmed and approved matches a month has."""
        try:
            counts = await service.counts(principal, bank_account_id, period)
        except HANDLED as error:
            raise http_error(error) from None
        return CountsView(
            free=counts.free,
            proposed=counts.proposed,
            confirmed=counts.confirmed,
            approved=counts.approved,
        )

    @router.get("/inbox/credits")
    async def list_free_credits(
        bank_account_id: Account,
        period: Period,
        principal: CurrentPrincipal,
        min_amount_cents: Cents = None,
        max_amount_cents: Cents = None,
        after: str | None = None,
        before: str | None = None,
        limit: Limit = 25,
    ) -> CreditPageView:
        """Credits of the month in no active match, by date (keyset pagination)."""
        filters = MatchFilters(min_amount_cents=min_amount_cents, max_amount_cents=max_amount_cents)
        try:
            page = await service.free_credits(
                principal,
                bank_account_id,
                period,
                filters,
                after=decode_date_cursor(after) if after else None,
                before=decode_date_cursor(before) if before else None,
                limit=limit,
            )
        except InvalidCursorError:
            raise _invalid_cursor() from None
        except HANDLED as error:
            raise http_error(error) from None
        items = page.credits
        return CreditPageView(
            credits=[_credit(item) for item in items],
            has_previous=page.has_previous,
            has_next=page.has_next,
            previous_cursor=encode_cursor(items[0].booked_on, items[0].id) if items else None,
            next_cursor=encode_cursor(items[-1].booked_on, items[-1].id) if items else None,
        )

    @router.get("/matches")
    async def list_matches(
        bank_account_id: Account,
        period: Period,
        principal: CurrentPrincipal,
        match_status: Annotated[
            Literal["proposed", "confirmed", "approved"], Query(alias="status")
        ] = "proposed",
        rule: Rule | None = None,
        min_score: Annotated[int | None, Query(ge=0, le=100)] = None,
        min_amount_cents: Cents = None,
        max_amount_cents: Cents = None,
        after: str | None = None,
        before: str | None = None,
        limit: Limit = 25,
    ) -> MatchPageView:
        """Matches of the month in one status, in the order they were created (engine proposals
        come out rule by rule). The amount filters apply to the sum of the credits."""
        filters = MatchFilters(rule, min_score, min_amount_cents, max_amount_cents)
        try:
            page = await service.matches(
                principal,
                bank_account_id,
                period,
                MatchStatus(match_status),
                filters,
                after=_match_cursor(after),
                before=_match_cursor(before),
                limit=limit,
            )
        except HANDLED as error:
            raise http_error(error) from None
        items = page.matches
        return MatchPageView(
            matches=[_match_row(item) for item in items],
            has_previous=page.has_previous,
            has_next=page.has_next,
            previous_cursor=str(items[0].id) if items else None,
            next_cursor=str(items[-1].id) if items else None,
        )

    @router.get("/inbox/receivables")
    async def list_open_receivables(
        principal: CurrentPrincipal,
        q: Annotated[str | None, Query(max_length=100)] = None,
        after: str | None = None,
        before: str | None = None,
        limit: Limit = 25,
    ) -> OpenReceivablePageView:
        """Live receivables with available balance, by due date, to reconcile by hand. `q`
        searches the document number, the customer name or the RUC."""
        try:
            page = await service.open_receivables(
                principal,
                q,
                after=decode_date_cursor(after) if after else None,
                before=decode_date_cursor(before) if before else None,
                limit=limit,
            )
        except InvalidCursorError:
            raise _invalid_cursor() from None
        except HANDLED as error:
            raise http_error(error) from None
        items = page.receivables
        return OpenReceivablePageView(
            receivables=[
                OpenReceivableView(
                    id=item.id,
                    doc_number=item.doc_number,
                    customer_name=item.customer_name,
                    customer_tax_id=item.customer_tax_id,
                    issued_on=item.issued_on,
                    due_on=item.due_on,
                    amount_cents=item.amount_cents,
                    available_cents=item.available_cents,
                )
                for item in items
            ],
            has_previous=page.has_previous,
            has_next=page.has_next,
            previous_cursor=encode_cursor(items[0].due_on, items[0].id) if items else None,
            next_cursor=encode_cursor(items[-1].due_on, items[-1].id) if items else None,
        )

    @router.get("/matches/{match_id}")
    async def get_match(match_id: UUID, principal: CurrentPrincipal) -> MatchDetailView:
        """A match with its credits, receivables, applied amounts, difference and decisions."""
        try:
            return _detail(await service.match_detail(principal, match_id))
        except HANDLED as error:
            raise http_error(error) from None

    return router
