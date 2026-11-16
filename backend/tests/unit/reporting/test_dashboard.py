from datetime import date, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from concilia.reporting.domain.dashboard import (
    AgeBucket,
    DayTotal,
    Tally,
    age_bucket,
    age_pending,
    month_end,
    reference_date,
)


@pytest.mark.parametrize(
    ("period", "end"),
    [
        (date(2027, 1, 1), date(2027, 1, 31)),
        (date(2027, 2, 1), date(2027, 2, 28)),
        (date(2028, 2, 1), date(2028, 2, 29)),
        (date(2027, 4, 1), date(2027, 4, 30)),
        (date(2027, 12, 1), date(2027, 12, 31)),
    ],
)
def test_a_month_ends_on_its_last_day(period: date, end: date) -> None:
    assert month_end(period) == end


def test_ages_are_measured_against_today_only_in_the_current_month() -> None:
    today = date(2027, 2, 3)

    assert reference_date(date(2027, 2, 1), today) == today
    assert reference_date(date(2027, 1, 1), today) == date(2027, 1, 31)
    assert reference_date(date(2027, 3, 1), today) == date(2027, 3, 31)


@pytest.mark.parametrize(
    ("days", "bucket"),
    [
        (0, AgeBucket.UP_TO_7),
        (7, AgeBucket.UP_TO_7),
        (8, AgeBucket.UP_TO_30),
        (30, AgeBucket.UP_TO_30),
        (31, AgeBucket.OVER_30),
        (400, AgeBucket.OVER_30),
    ],
)
def test_age_buckets_include_their_upper_bound(days: int, bucket: AgeBucket) -> None:
    assert age_bucket(days) == bucket


@given(
    st.lists(
        st.tuples(
            st.integers(min_value=0, max_value=120),
            st.integers(min_value=1, max_value=50),
            st.integers(min_value=1, max_value=10**12),
        ),
        max_size=40,
    )
)
def test_aging_keeps_every_pending_credit_in_exactly_one_bucket(
    days: list[tuple[int, int, int]],
) -> None:
    reference = date(2027, 3, 31)
    totals = [DayTotal(reference - timedelta(days=age), count, cents) for age, count, cents in days]

    buckets = age_pending(totals, reference)

    assert set(buckets) == set(AgeBucket)
    assert sum(t.count for t in buckets.values()) == sum(t.count for t in totals)
    assert sum(t.cents for t in buckets.values()) == sum(t.cents for t in totals)
    for bucket, tally in buckets.items():
        expected = [
            t for t, (age, _, _) in zip(totals, days, strict=True) if age_bucket(age) == bucket
        ]
        assert tally == Tally(sum(t.count for t in expected), sum(t.cents for t in expected))
