from datetime import UTC, date, datetime

from concilia.shared.kernel.clock import lima_date


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def today_lima(self) -> date:
        return lima_date(self.now())
