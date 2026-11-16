from datetime import date, datetime, time
from typing import Protocol
from zoneinfo import ZoneInfo

LIMA = ZoneInfo("America/Lima")


class Clock(Protocol):
    def now(self) -> datetime: ...

    def today_lima(self) -> date: ...


def lima_date(instant: datetime) -> date:
    if instant.tzinfo is None:
        raise ValueError("instant must be timezone-aware")
    return instant.astimezone(LIMA).date()


def lima_day_start(day: date) -> datetime:
    return datetime.combine(day, time(), LIMA)
