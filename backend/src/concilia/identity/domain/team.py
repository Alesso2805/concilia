import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from concilia.identity.domain.model import Role

INVITATION_LIFETIME = timedelta(days=7)
EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


class InvalidEmailError(ValueError):
    pass


class NoRolesError(ValueError):
    pass


class LastAdminError(Exception):
    pass


def parse_roles(values: Iterable[str]) -> frozenset[Role]:
    roles = frozenset(Role(value) for value in values)
    if not roles:
        raise NoRolesError
    return roles


def check_email(email: str) -> str:
    if EMAIL_PATTERN.fullmatch(email) is None:
        raise InvalidEmailError
    return email


@dataclass(frozen=True)
class Member:
    user_id: UUID
    display_name: str
    email: str
    roles: frozenset[Role]
    joined_at: datetime


@dataclass(frozen=True)
class Invitation:
    id: UUID
    organization_id: UUID
    email: str
    roles: frozenset[Role]
    created_by: UUID
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None

    def is_pending(self, now: datetime) -> bool:
        return self.accepted_at is None and self.revoked_at is None and now < self.expires_at


def ensure_an_admin_remains(
    roles_by_member: Mapping[UUID, frozenset[Role]],
    user_id: UUID,
    new_roles: frozenset[Role],
) -> None:
    after = {**roles_by_member, user_id: new_roles}
    if not any(Role.ADMIN in roles for roles in after.values()):
        raise LastAdminError
