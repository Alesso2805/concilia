import logging
import sys
import traceback
from collections.abc import MutableMapping
from pathlib import PurePath
from types import TracebackType
from typing import Any, TextIO

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

ALLOWED_FIELDS = frozenset(
    {
        "event",
        "level",
        "timestamp",
        "logger",
        "request_id",
        "method",
        "route",
        "status_code",
        "duration_ms",
        "organization_id",
        "user_id",
        "job_id",
        "job_kind",
        "attempt",
        "error_code",
        "row_count",
        "progress",
        "exception_type",
        "exception_frames",
        "dropped_fields",
    }
)

FORMATTER_META_FIELDS = frozenset({"_record", "_from_structlog"})
EXCEPTION_FIELDS = ("exc_info", "exception", "stack", "stack_info")


def _resolve_exception(value: object) -> BaseException | None:
    if isinstance(value, BaseException):
        return value
    if value is True:
        return sys.exception()
    if isinstance(value, tuple) and len(value) == 3 and isinstance(value[1], BaseException):
        return value[1]
    return None


def _frames(tb: TracebackType | None) -> list[str]:
    return [
        f"{PurePath(frame.filename).name}:{frame.lineno} in {frame.name}"
        for frame in traceback.extract_tb(tb)
    ]


def describe_exception_without_message(
    _logger: WrappedLogger, _method: str, event_dict: EventDict
) -> EventDict:
    exception = _resolve_exception(event_dict.get("exc_info"))
    for field in EXCEPTION_FIELDS:
        event_dict.pop(field, None)
    if exception is not None:
        exc_type = type(exception)
        event_dict["exception_type"] = f"{exc_type.__module__}.{exc_type.__qualname__}"
        event_dict["exception_frames"] = _frames(exception.__traceback__)
    return event_dict


def keep_allowed_fields(
    _logger: WrappedLogger, _method: str, event_dict: EventDict
) -> MutableMapping[str, Any]:
    allowed = ALLOWED_FIELDS | FORMATTER_META_FIELDS
    dropped = sorted(key for key in event_dict if key not in allowed)
    kept = {key: value for key, value in event_dict.items() if key in allowed}
    if dropped:
        kept["dropped_fields"] = dropped
    return kept


def shared_processors() -> list[Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        describe_exception_without_message,
        keep_allowed_fields,
    ]


def configure_logging(level: int = logging.INFO, stream: TextIO | None = None) -> None:
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors(),
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(),
            ],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    structlog.configure(
        processors=[
            *shared_processors(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
