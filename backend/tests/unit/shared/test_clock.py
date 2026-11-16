from datetime import UTC, date, datetime, timedelta

import pytest
import time_machine

from concilia.shared.infrastructure.clock import SystemClock
from concilia.shared.kernel.clock import lima_date


def test_now_is_utc() -> None:
    assert SystemClock().now().utcoffset() == timedelta(0)


@time_machine.travel(datetime(2026, 12, 1, 4, 59, 59, tzinfo=UTC), tick=False)
def test_today_lima_is_still_the_previous_day_before_five_utc() -> None:
    assert SystemClock().today_lima() == date(2026, 11, 30)


@time_machine.travel(datetime(2026, 12, 1, 5, 0, tzinfo=UTC), tick=False)
def test_today_lima_changes_at_five_utc() -> None:
    assert SystemClock().today_lima() == date(2026, 12, 1)


@pytest.mark.parametrize(
    ("instant", "expected"),
    [
        (datetime(2028, 3, 1, 4, 0, tzinfo=UTC), date(2028, 2, 29)),
        (datetime(2027, 1, 1, 4, 30, tzinfo=UTC), date(2026, 12, 31)),
        (datetime(2027, 3, 1, 4, 0, tzinfo=UTC), date(2027, 2, 28)),
    ],
)
def test_lima_date_handles_month_year_and_leap_day_boundaries(
    instant: datetime, expected: date
) -> None:
    assert lima_date(instant) == expected


def test_lima_date_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        lima_date(datetime(2026, 1, 1))  # noqa: DTZ001
