import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

CURRENCY = "PEN"
LAST4 = re.compile(r"[0-9]{4}")


class ProfileKind(StrEnum):
    BANK_STATEMENT = "bank_statement"
    RECEIVABLES = "receivables"


class InvalidLast4Error(ValueError):
    pass


def check_last4(value: str) -> str:
    if LAST4.fullmatch(value) is None:
        raise InvalidLast4Error
    return value


@dataclass(frozen=True)
class BankAccount:
    id: UUID
    bank: str
    alias: str
    number_last4: str
    created_at: datetime
    archived_at: datetime | None
    currency: str = CURRENCY


@dataclass(frozen=True)
class ImportProfile:
    id: UUID
    kind: ProfileKind
    bank_account_id: UUID | None
    name: str
    config: Mapping[str, Any]
    created_at: datetime
    archived_at: datetime | None
