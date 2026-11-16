from datetime import UTC, date, datetime
from uuid import UUID, uuid7

import pytest
from hypothesis import given
from hypothesis import strategies as st

from concilia.shared.kernel.cursor import (
    InvalidCursorError,
    decode_cursor,
    decode_date_cursor,
    encode_cursor,
)


@given(st.datetimes(timezones=st.just(UTC)), st.uuids())
def test_cursors_round_trip(moment: datetime, row_id: UUID) -> None:
    assert decode_cursor(encode_cursor(moment, row_id)) == (moment, row_id)


@pytest.mark.parametrize("cursor", ["", "%%%", "bm90IGEgY3Vyc29y", "MjAyNy0wMS0wNXxub3QtYS11dWlk"])
def test_malformed_cursors_are_rejected(cursor: str) -> None:
    with pytest.raises(InvalidCursorError):
        decode_cursor(cursor)


def test_naive_timestamps_are_rejected() -> None:
    naive = encode_cursor(datetime(2027, 1, 5), uuid7())  # noqa: DTZ001 - the case under test

    with pytest.raises(InvalidCursorError):
        decode_cursor(naive)


@given(st.dates(), st.uuids())
def test_date_cursors_round_trip(day: date, row_id: UUID) -> None:
    assert decode_date_cursor(encode_cursor(day, row_id)) == (day, row_id)


def test_a_timestamp_is_not_a_date_cursor() -> None:
    with pytest.raises(InvalidCursorError):
        decode_date_cursor(encode_cursor(datetime(2027, 1, 5, tzinfo=UTC), uuid7()))
