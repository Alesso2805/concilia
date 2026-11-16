from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from concilia.reporting.domain.dashboard import Dashboard

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

STATUS_LABELS = {
    "free": "Sin conciliar",
    "proposed": "Propuesto",
    "confirmed": "Confirmado",
    "approved": "Aprobado",
}
REASON_LABELS = {
    "commission": "Comisión",
    "detraction": "Detracción",
    "rounding": "Redondeo",
    "overpayment": "Sobrepago",
    "other": "Otro",
}
SOURCE_LABELS = {"engine": "Motor", "manual": "A mano", "ai": "Sugerencia de IA"}
AGE_LABELS = {"0-7": "0 a 7 días", "8-30": "8 a 30 días", "31+": "Más de 30 días"}


def neutralize(value: str) -> str:
    """A spreadsheet must show text as text: a leading apostrophe keeps a value such as
    `=HYPERLINK(...)` from being read as a formula (rule 8)."""
    return f"'{value}" if value.startswith(FORMULA_PREFIXES) else value


def percent_text(part: int, total: int) -> str:
    """Rounded down to a tenth of a percent, as in the dashboard."""
    if total <= 0:
        return "—"
    tenths = part * 1000 // total
    return f"{tenths // 10}.{tenths % 10} %"


@dataclass(frozen=True)
class MatchLine:
    match_id: UUID
    status: str
    source: str
    rule: str | None
    booked_on: date
    descriptions: list[str]
    credits_cents: int
    documents: list[str]
    customers: list[str]
    applied_cents: int
    difference_reason: str | None
    confirmed_by: str | None
    confirmed_at: datetime | None
    approved_by: str | None
    approved_at: datetime | None

    @property
    def difference_cents(self) -> int:
        return self.credits_cents - self.applied_cents

    @property
    def origin(self) -> str:
        label = SOURCE_LABELS.get(self.source, self.source)
        return f"{label} ({self.rule})" if self.rule else label


@dataclass(frozen=True)
class PendingLine:
    booked_on: date
    description: str
    operation_number: str | None
    amount_cents: int
    status: str


@dataclass(frozen=True)
class PeriodReport:
    account: str
    generated_at: datetime
    dashboard: Dashboard
    reconciled: list[MatchLine]
    pending: list[PendingLine]
    differences: list[MatchLine]
