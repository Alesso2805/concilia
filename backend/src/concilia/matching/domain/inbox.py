from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID


class MatchStatus(StrEnum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    APPROVED = "approved"
    DISCARDED = "discarded"
    REJECTED = "rejected"
    REVERTED = "reverted"


INBOX_STATUSES = (MatchStatus.PROPOSED, MatchStatus.CONFIRMED, MatchStatus.APPROVED)


@dataclass(frozen=True)
class PeriodSummary:
    period: date
    closed: bool
    credits: int


@dataclass(frozen=True)
class InboxCounts:
    free: int
    proposed: int
    confirmed: int
    approved: int


@dataclass(frozen=True)
class MatchFilters:
    rule: str | None = None
    min_score: int | None = None
    min_amount_cents: int | None = None
    max_amount_cents: int | None = None


@dataclass(frozen=True)
class CreditRow:
    id: UUID
    booked_on: date
    description: str
    operation_number: str | None
    amount_cents: int


@dataclass(frozen=True)
class CreditPage:
    credits: list[CreditRow]
    has_previous: bool
    has_next: bool


@dataclass(frozen=True)
class MatchRow:
    id: UUID
    source: str
    rule: str | None
    score: int | None
    status: MatchStatus
    booked_on: date
    description: str
    documents: tuple[str, ...]
    customers: tuple[str, ...]
    credits_cents: int
    applied_cents: int

    @property
    def difference_cents(self) -> int:
        return self.credits_cents - self.applied_cents


@dataclass(frozen=True)
class MatchPage:
    matches: list[MatchRow]
    has_previous: bool
    has_next: bool


@dataclass(frozen=True)
class MatchedReceivable:
    id: UUID
    doc_number: str
    customer_name: str
    due_on: date
    amount_cents: int
    applied_cents: int
    available_cents: int


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str | None
    difference_reason: str | None
    difference_note: str | None
    decided_by: str
    decided_at: datetime


@dataclass(frozen=True)
class MatchDetail:
    id: UUID
    bank_account_id: UUID
    source: str
    rule: str | None
    score: int | None
    status: MatchStatus
    suggested_difference_reason: str | None
    explanation: str | None
    created_at: datetime
    credits: list[CreditRow]
    receivables: list[MatchedReceivable]
    decisions: list[Decision]

    @property
    def difference_cents(self) -> int:
        return sum(credit.amount_cents for credit in self.credits) - sum(
            receivable.applied_cents for receivable in self.receivables
        )


@dataclass(frozen=True)
class OpenReceivable:
    id: UUID
    doc_number: str
    customer_name: str
    customer_tax_id: str | None
    issued_on: date
    due_on: date
    amount_cents: int
    available_cents: int


@dataclass(frozen=True)
class OpenReceivablePage:
    receivables: list[OpenReceivable]
    has_previous: bool
    has_next: bool
