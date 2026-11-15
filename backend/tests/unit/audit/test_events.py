from datetime import UTC, datetime
from uuid import uuid7

import pytest

from concilia.audit.domain.events import AuditAction, AuditEvent, AuditMetadataError

NOW = datetime(2026, 11, 23, tzinfo=UTC)


def _event(metadata: dict[str, str | list[str]]) -> AuditEvent:
    return AuditEvent(
        uuid7(),
        uuid7(),
        None,
        AuditAction.ORGANIZATION_CREATED,
        "organization",
        None,
        NOW,
        metadata,
    )


def test_allowed_metadata_keys_are_accepted() -> None:
    assert (
        _event({"source": "registration", "roles": ["admin"]}).metadata["source"] == "registration"
    )


@pytest.mark.parametrize("key", ["customer_name", "description", "amount_cents", "email"])
def test_metadata_with_customer_data_keys_is_rejected(key: str) -> None:
    with pytest.raises(AuditMetadataError):
        _event({key: "x"})
