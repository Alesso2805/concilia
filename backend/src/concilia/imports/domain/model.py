from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class FileStatus(StrEnum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    PREVIEWED = "previewed"
    FAILED = "failed"
    CONFIRMED = "confirmed"
    DISCARDED = "discarded"
    VOIDED = "voided"


class RowStatus(StrEnum):
    OK = "ok"
    ERROR = "error"
    DUPLICATE = "duplicate"
    CLOSED_PERIOD = "closed_period"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class ImportFile:
    id: UUID
    kind: str
    bank_account_id: UUID | None
    import_profile_id: UUID
    profile_snapshot: Mapping[str, Any]
    filename: str
    sha256: str
    size_bytes: int
    status: FileStatus
    error_code: str | None
    row_count: int | None
    created_by: UUID
    created_at: datetime
    confirmed_at: datetime | None = None
    discarded_at: datetime | None = None
    voided_at: datetime | None = None


@dataclass(frozen=True)
class ImportRow:
    row_number: int
    status: RowStatus
    parsed: Mapping[str, Any]
    error_code: str | None = None


@dataclass(frozen=True)
class RowPage:
    rows: list[ImportRow]
    has_previous: bool
    has_next: bool
