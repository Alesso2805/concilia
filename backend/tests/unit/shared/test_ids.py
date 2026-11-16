from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4, uuid7

import pytest
import time_machine

from concilia.shared.kernel.ids import (
    ClientIdError,
    IdConflictError,
    create_or_replay,
    uuid7_instant,
    validate_client_id,
)

NOW = datetime(2026, 11, 23, 14, 0, tzinfo=UTC)


def _uuid7_at(instant: datetime) -> UUID:
    with time_machine.travel(instant, tick=False):
        return uuid7()


def test_uuid7_instant_reads_the_embedded_millisecond() -> None:
    assert uuid7_instant(_uuid7_at(NOW)) == NOW


@pytest.mark.parametrize("skew", [timedelta(0), timedelta(hours=23), -timedelta(hours=23)])
def test_recent_uuid7_ids_are_accepted(skew: timedelta) -> None:
    value = _uuid7_at(NOW + skew)

    assert validate_client_id(value, NOW) == value


@pytest.mark.parametrize(
    ("value", "code"),
    [
        (uuid4(), "id_not_uuid7"),
        (_uuid7_at(NOW - timedelta(days=1, seconds=1)), "id_clock_skew"),
        (_uuid7_at(NOW + timedelta(days=2)), "id_clock_skew"),
    ],
)
def test_other_ids_are_rejected(value: UUID, code: str) -> None:
    with pytest.raises(ClientIdError) as error:
        validate_client_id(value, NOW)

    assert error.value.code == code


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("existing", "same", "expected"), [(None, False, ("new", True)), ("old", True, ("old", False))]
)
async def test_create_or_replay(
    existing: str | None, same: bool, expected: tuple[str, bool]
) -> None:
    async def find() -> str | None:
        return existing

    async def create() -> str:
        return "new"

    result = await create_or_replay(find=find, create=create, same_content=lambda _: same)

    assert result == expected


@pytest.mark.anyio
async def test_create_or_replay_rejects_the_same_id_with_other_content() -> None:
    async def find() -> str | None:
        return "old"

    async def create() -> str:
        return "new"

    with pytest.raises(IdConflictError):
        await create_or_replay(find=find, create=create, same_content=lambda _: False)
