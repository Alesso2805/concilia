from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from uuid import UUID


class Rule(StrEnum):
    EXACT = "R1"
    SEVERAL_DOCUMENTS = "R2"
    REFERENCE_WITH_DIFFERENCE = "R3"
    SAME_CUSTOMER = "R4"
    PAID_IN_PARTS = "R5"
    AMOUNT_AND_DATE = "R6"


class DifferenceReason(StrEnum):
    COMMISSION = "commission"
    DETRACTION = "detraction"
    ROUNDING = "rounding"
    OVERPAYMENT = "overpayment"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class Credit:
    id: UUID
    booked_on: date
    amount_cents: int
    description_norm: str
    doc_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.amount_cents <= 0:
            raise ValueError("credits have a positive amount")
        if len(set(self.doc_refs)) != len(self.doc_refs):
            raise ValueError("credit document references are unique")


@dataclass(frozen=True, slots=True)
class OpenReceivable:
    id: UUID
    doc_number_norm: str
    customer_name_norm: str
    customer_tax_id: str | None
    issued_on: date
    due_on: date
    available_cents: int

    def __post_init__(self) -> None:
        if self.available_cents <= 0:
            raise ValueError("open receivables have a positive available balance")


@dataclass(frozen=True, slots=True)
class EnginePolicy:
    tolerance_min_cents: int = 100
    tolerance_bp: int = 50
    detraction_rates_bp: tuple[int, ...] = (1000, 1200)


@dataclass(frozen=True, slots=True)
class MatchKey:
    credit_ids: frozenset[UUID]
    receivable_ids: frozenset[UUID]


@dataclass(frozen=True, slots=True)
class Application:
    receivable_id: UUID
    applied_cents: int


@dataclass(frozen=True, slots=True)
class Proposal:
    rule: Rule
    score: int
    credit_ids: tuple[UUID, ...]
    applications: tuple[Application, ...]
    difference_cents: int
    suggested_difference_reason: DifferenceReason | None
    explanation: str

    @property
    def key(self) -> MatchKey:
        return MatchKey(
            frozenset(self.credit_ids),
            frozenset(application.receivable_id for application in self.applications),
        )


@dataclass(frozen=True, slots=True)
class EngineInput:
    period: date
    credits: tuple[Credit, ...]
    receivables: tuple[OpenReceivable, ...]
    policy: EnginePolicy = field(default_factory=EnginePolicy)
    excluded: frozenset[MatchKey] = frozenset()

    def __post_init__(self) -> None:
        if self.period.day != 1:
            raise ValueError("a period starts on the first day of its month")
        if any(credit.booked_on.replace(day=1) != self.period for credit in self.credits):
            raise ValueError("every credit belongs to the period")
        ids = Counter([c.id for c in self.credits] + [r.id for r in self.receivables])
        if any(count > 1 for count in ids.values()):
            raise ValueError("credit and receivable ids are unique")
        documents = Counter(receivable.doc_number_norm for receivable in self.receivables)
        if any(count > 1 for count in documents.values()):
            raise ValueError("receivable document numbers are unique")
