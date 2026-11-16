from contextlib import AbstractAsyncContextManager
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from concilia.audit.application.recorder import AuditRecorder
from concilia.identity.domain.model import OrganizationAccess, Role, Session, User
from concilia.identity.domain.settings import OrganizationSettings


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...

    def verify(self, password_hash: str, password: str) -> bool: ...

    def needs_rehash(self, password_hash: str) -> bool: ...


class IdentityStore(Protocol):
    audit: AuditRecorder

    async def lock_organization(self, organization_id: UUID) -> None: ...

    async def find_user_by_email(self, email: str) -> User | None: ...

    async def find_user(self, user_id: UUID) -> User | None: ...

    async def insert_user(self, user: User, *, is_demo: bool, now: datetime) -> None: ...

    async def update_password_hash(self, user_id: UUID, password_hash: str) -> None: ...

    async def find_organization_name(self, organization_id: UUID) -> str | None: ...

    async def organization_settings(self, organization_id: UUID) -> OrganizationSettings | None: ...

    async def update_organization_settings(
        self, organization_id: UUID, settings: OrganizationSettings
    ) -> None: ...

    async def insert_organization(
        self,
        organization_id: UUID,
        name: str,
        now: datetime,
        *,
        demo_expires_at: datetime | None = None,
    ) -> None: ...

    async def insert_membership(
        self, organization_id: UUID, user_id: UUID, roles: frozenset[Role], now: datetime
    ) -> None: ...

    async def is_admin(self, organization_id: UUID, user_id: UUID) -> bool: ...

    async def user_organizations(self, user_id: UUID) -> list[OrganizationAccess]: ...

    async def demo_user_for_role(
        self, organization_id: UUID, current_user_id: UUID, role: str, now: datetime
    ) -> UUID | None:
        """The demo user with `role` when the organization is a live demo and the current user
        is one of its demo users; otherwise None."""
        ...

    async def insert_session(self, session: Session, token_hash: str) -> None: ...

    async def find_session(self, token_hash: str) -> Session | None: ...

    async def touch_session(self, session_id: UUID, now: datetime) -> None: ...

    async def revoke_session(self, session_id: UUID, now: datetime) -> None: ...


class IdentityTransactions(Protocol):
    def anonymous(self) -> AbstractAsyncContextManager[IdentityStore]: ...

    def organization(self, organization_id: UUID) -> AbstractAsyncContextManager[IdentityStore]: ...


class RateLimiter(Protocol):
    async def hit(self, key: str, window: timedelta, now: datetime) -> int: ...
