from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

SESSION_IDLE_LIMIT = timedelta(hours=12)
SESSION_ABSOLUTE_LIMIT = timedelta(days=7)
SESSION_TOUCH_INTERVAL = timedelta(minutes=5)
MIN_PASSWORD_LENGTH = 12


class Role(StrEnum):
    ADMIN = "admin"
    ANALYST = "analyst"
    REVIEWER = "reviewer"


def normalize_email(email: str) -> str:
    return email.strip().lower()


@dataclass(frozen=True)
class User:
    id: UUID
    email: str
    password_hash: str | None
    display_name: str


@dataclass(frozen=True)
class OrganizationAccess:
    organization_id: UUID
    name: str
    is_demo: bool
    roles: frozenset[Role]


@dataclass(frozen=True)
class Session:
    id: UUID
    user_id: UUID
    organization_id: UUID | None
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    revoked_at: datetime | None

    def is_active(self, now: datetime) -> bool:
        return (
            self.revoked_at is None
            and now < self.expires_at
            and now < self.last_seen_at + SESSION_IDLE_LIMIT
        )

    def needs_touch(self, now: datetime) -> bool:
        return now >= self.last_seen_at + SESSION_TOUCH_INTERVAL


def session_expiry(created_at: datetime) -> datetime:
    return created_at + SESSION_ABSOLUTE_LIMIT
