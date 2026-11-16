from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Protocol
from uuid import UUID

from concilia.audit.domain.events import AuditAction, AuditEntity
from concilia.shared.kernel.clock import lima_day_start
from concilia.shared.kernel.principal import Principal

__all__ = [
    "Actor",
    "AuditAction",
    "AuditEntity",
    "AuditEntry",
    "AuditFilters",
    "AuditLogService",
    "AuditLogStore",
    "AuditLogTransactions",
    "AuditPage",
    "AuditorRequiredError",
    "InvalidRangeError",
]

VIEWER_ROLES = frozenset({"admin", "analyst", "reviewer"})


class AuditorRequiredError(Exception):
    pass


class InvalidRangeError(Exception):
    pass


@dataclass(frozen=True)
class AuditFilters:
    actor_user_id: UUID | None = None
    action: AuditAction | None = None
    entity: AuditEntity | None = None
    from_day: date | None = None
    to_day: date | None = None


@dataclass(frozen=True)
class AuditEntry:
    id: UUID
    seq: int
    at: datetime
    actor_user_id: UUID | None
    actor_name: str | None
    action: str
    entity: str
    entity_id: UUID | None
    metadata: Mapping[str, str | list[str]]


@dataclass(frozen=True)
class AuditPage:
    entries: list[AuditEntry]
    has_previous: bool
    has_next: bool


@dataclass(frozen=True)
class Actor:
    user_id: UUID
    display_name: str


class AuditLogStore(Protocol):
    async def page(
        self,
        actor_user_id: UUID | None,
        action: str | None,
        entity: str | None,
        since: datetime | None,
        until: datetime | None,
        after: int | None,
        before: int | None,
        limit: int,
    ) -> AuditPage: ...

    async def actors(self) -> list[Actor]: ...


class AuditLogTransactions(Protocol):
    def organization(self, organization_id: UUID) -> AbstractAsyncContextManager[AuditLogStore]: ...


def _organization(principal: Principal) -> UUID:
    if principal.organization_id is None or not principal.roles & VIEWER_ROLES:
        raise AuditorRequiredError
    return principal.organization_id


class AuditLogService:
    def __init__(self, transactions: AuditLogTransactions) -> None:
        self._transactions = transactions

    async def page(
        self,
        principal: Principal,
        filters: AuditFilters,
        *,
        after: int | None,
        before: int | None,
        limit: int,
    ) -> AuditPage:
        """Newest first; `from_day` and `to_day` are Lima days, both included."""
        organization_id = _organization(principal)
        if filters.from_day and filters.to_day and filters.from_day > filters.to_day:
            raise InvalidRangeError
        since = lima_day_start(filters.from_day) if filters.from_day else None
        until = lima_day_start(filters.to_day + timedelta(days=1)) if filters.to_day else None
        async with self._transactions.organization(organization_id) as store:
            return await store.page(
                filters.actor_user_id,
                filters.action.value if filters.action else None,
                filters.entity.value if filters.entity else None,
                since,
                until,
                after,
                before,
                limit,
            )

    async def actors(self, principal: Principal) -> list[Actor]:
        """Everyone who is or was a member, to filter by who acted."""
        organization_id = _organization(principal)
        async with self._transactions.organization(organization_id) as store:
            return await store.actors()
