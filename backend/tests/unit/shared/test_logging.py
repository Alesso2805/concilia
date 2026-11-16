import io
import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest
import structlog
from hypothesis import given
from hypothesis import strategies as st

from concilia.shared.infrastructure.logging import (
    ALLOWED_FIELDS,
    EXCEPTION_FIELDS,
    configure_logging,
)

CUSTOMER_TEXT = "ACME SAC PAGO F001-123 S/ 1234.56"


@pytest.fixture
def output() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    configure_logging(stream=stream)
    yield stream
    structlog.reset_defaults()
    logging.getLogger().handlers = []


def _records(stream: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_customer_data_fields_are_dropped(output: io.StringIO) -> None:
    structlog.get_logger("test").info(
        "match_proposed",
        job_id="j1",
        customer_name="ACME SAC",
        description="PAGO F001-123",
        amount_cents=123456,
        prompt="system prompt",
    )

    [record] = _records(output)
    assert record["event"] == "match_proposed"
    assert record["job_id"] == "j1"
    assert record["dropped_fields"] == ["amount_cents", "customer_name", "description", "prompt"]
    assert "ACME" not in output.getvalue()
    assert "123456" not in output.getvalue()


def test_exception_messages_are_never_logged(output: io.StringIO) -> None:
    log = structlog.get_logger("test")
    try:
        raise ValueError(CUSTOMER_TEXT)
    except ValueError:
        log.exception("import_failed", error_code="parse_error")

    [record] = _records(output)
    assert record["exception_type"] == "builtins.ValueError"
    assert record["exception_frames"][0].startswith("test_logging.py:")
    assert record["error_code"] == "parse_error"
    assert "ACME" not in output.getvalue()


def test_standard_library_loggers_go_through_the_allowlist(output: io.StringIO) -> None:
    logging.getLogger("uvicorn.error").warning(
        "worker_stopped", extra={"description": CUSTOMER_TEXT}
    )

    [record] = _records(output)
    assert record["logger"] == "uvicorn.error"
    assert "ACME" not in output.getvalue()


@given(
    fields=st.dictionaries(
        st.from_regex(r"[a-z][a-z_]{0,15}", fullmatch=True).filter(
            lambda key: key not in ALLOWED_FIELDS and key not in EXCEPTION_FIELDS
        ),
        st.text(alphabet="XYZQ", min_size=8, max_size=12),
        min_size=1,
        max_size=5,
    )
)
def test_no_field_outside_the_allowlist_reaches_the_output(fields: dict[str, str]) -> None:
    stream = io.StringIO()
    configure_logging(stream=stream)
    try:
        structlog.get_logger("test").info("event_name", **fields)
    finally:
        structlog.reset_defaults()
        logging.getLogger().handlers = []

    [record] = _records(stream)
    assert set(record) <= ALLOWED_FIELDS
    assert record["dropped_fields"] == sorted(fields)
    assert not any(value in stream.getvalue() for value in fields.values())
