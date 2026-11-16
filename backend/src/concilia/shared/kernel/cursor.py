from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import date, datetime
from uuid import UUID

SEPARATOR = "|"


class InvalidCursorError(ValueError):
    pass


def encode_cursor(sort_value: date, row_id: UUID) -> str:
    raw = f"{sort_value.isoformat()}{SEPARATOR}{row_id}"
    return urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        raw = urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        sort_value, row_id = raw.split(SEPARATOR)
        parsed = datetime.fromisoformat(sort_value)
        if parsed.tzinfo is None:
            raise InvalidCursorError
        return parsed, UUID(row_id)
    except (ValueError, UnicodeDecodeError) as error:
        raise InvalidCursorError from error


def decode_date_cursor(cursor: str) -> tuple[date, UUID]:
    try:
        raw = urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        sort_value, row_id = raw.split(SEPARATOR)
        return date.fromisoformat(sort_value), UUID(row_id)
    except (ValueError, UnicodeDecodeError) as error:
        raise InvalidCursorError from error
