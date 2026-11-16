from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum


class CreditStatus(StrEnum):
    FREE = "free"
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    APPROVED = "approved"


class AgeBucket(StrEnum):
    UP_TO_7 = "0-7"
    UP_TO_30 = "8-30"
    OVER_30 = "31+"


@dataclass(frozen=True)
class Tally:
    count: int = 0
    cents: int = 0

    def plus(self, count: int, cents: int) -> Tally:
        return Tally(self.count + count, self.cents + cents)


@dataclass(frozen=True)
class DayTotal:
    """Pending credits booked on one day."""

    booked_on: date
    count: int
    cents: int


@dataclass(frozen=True)
class DifferenceTotal:
    reason: str
    count: int
    cents: int


@dataclass(frozen=True)
class Dashboard:
    period: date
    reference_date: date
    closed: bool
    credits: dict[CreditStatus, Tally]
    pending: dict[AgeBucket, Tally]
    differences: list[DifferenceTotal] = field(default_factory=list)


def month_end(period: date) -> date:
    following = (period.replace(day=28) + timedelta(days=4)).replace(day=1)
    return following - timedelta(days=1)


def reference_date(period: date, today: date) -> date:
    """Ages are measured against the last day of the period, or today in the current month."""
    if today.replace(day=1) == period:
        return today
    return month_end(period)


def age_bucket(days: int) -> AgeBucket:
    if days <= 7:
        return AgeBucket.UP_TO_7
    if days <= 30:
        return AgeBucket.UP_TO_30
    return AgeBucket.OVER_30


def age_pending(days: Iterable[DayTotal], reference: date) -> dict[AgeBucket, Tally]:
    buckets = dict.fromkeys(AgeBucket, Tally())
    for day in days:
        bucket = age_bucket((reference - day.booked_on).days)
        buckets[bucket] = buckets[bucket].plus(day.count, day.cents)
    return buckets
