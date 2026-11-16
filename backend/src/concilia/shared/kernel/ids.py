from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import RFC_4122, UUID

MAX_CLIENT_CLOCK_SKEW = timedelta(days=1)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class ClientIdError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class IdConflictError(Exception):
    pass


def uuid7_instant(value: UUID) -> datetime:
    return _EPOCH + timedelta(milliseconds=value.int >> 80)


def validate_client_id(value: UUID, now: datetime) -> UUID:
    if value.version != 7 or value.variant != RFC_4122:
        raise ClientIdError("id_not_uuid7")
    if abs(uuid7_instant(value) - now) > MAX_CLIENT_CLOCK_SKEW:
        raise ClientIdError("id_clock_skew")
    return value


async def create_or_replay[T](
    *,
    find: Callable[[], Awaitable[T | None]],
    create: Callable[[], Awaitable[T]],
    same_content: Callable[[T], bool],
) -> tuple[T, bool]:
    existing = await find()
    if existing is None:
        return await create(), True
    if same_content(existing):
        return existing, False
    raise IdConflictError
