from datetime import UTC, date, datetime, timedelta

from concilia.shared.kernel.clock import lima_date


class FixedClock:
    def __init__(self, instant: datetime) -> None:
        if instant.utcoffset() != timedelta(0):
            raise ValueError("FixedClock needs a UTC instant")
        self._instant = instant.astimezone(UTC)

    def now(self) -> datetime:
        return self._instant

    def today_lima(self) -> date:
        return lima_date(self._instant)

    def advance(self, delta: timedelta) -> None:
        self._instant += delta
