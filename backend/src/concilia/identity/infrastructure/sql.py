from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from concilia.audit.application.recorder import AuditRecorder
from concilia.identity.domain.model import OrganizationAccess, Role, Session, User
from concilia.identity.domain.settings import OrganizationSettings
from concilia.shared.infrastructure.db import (
    anonymous_transaction,
    lock_organization,
    organization_transaction,
)
from concilia.shared.kernel.ids import IdConflictError

type AuditRecorderFactory = Callable[[AsyncConnection], AuditRecorder]


class SqlIdentityStore:
    def __init__(self, connection: AsyncConnection, audit: AuditRecorder) -> None:
        self._connection = connection
        self.audit = audit

    async def _execute(self, sql: str, **params: object) -> None:
        await self._connection.execute(text(sql), params)

    async def lock_organization(self, organization_id: UUID) -> None:
        await lock_organization(self._connection, organization_id)

    async def _user(self, where: str, value: object) -> User | None:
        row = (
            await self._connection.execute(
                text(f"SELECT id, email, password_hash, display_name FROM users WHERE {where}"),  # noqa: S608
                {"value": value},
            )
        ).first()
        return None if row is None else User(row.id, row.email, row.password_hash, row.display_name)

    async def find_user_by_email(self, email: str) -> User | None:
        return await self._user("lower(email) = :value", email)

    async def find_user(self, user_id: UUID) -> User | None:
        return await self._user("id = :value", user_id)

    async def insert_user(self, user: User, *, is_demo: bool, now: datetime) -> None:
        await self._execute(
            """INSERT INTO users (id, email, password_hash, display_name, is_demo, created_at)
               VALUES (:id, :email, :password_hash, :display_name, :is_demo, :now)""",
            id=user.id,
            email=user.email,
            password_hash=user.password_hash,
            display_name=user.display_name,
            is_demo=is_demo,
            now=now,
        )

    async def update_password_hash(self, user_id: UUID, password_hash: str) -> None:
        await self._execute(
            "UPDATE users SET password_hash = :hash WHERE id = :id", hash=password_hash, id=user_id
        )

    async def find_organization_name(self, organization_id: UUID) -> str | None:
        result = await self._connection.execute(
            text("SELECT name FROM organizations WHERE id = :id"), {"id": organization_id}
        )
        name: str | None = result.scalar_one_or_none()
        return name

    async def organization_settings(self, organization_id: UUID) -> OrganizationSettings | None:
        row = (
            await self._connection.execute(
                text(
                    """SELECT name, tolerance_min_cents, tolerance_bp, detraction_rates_bp
                       FROM organizations WHERE id = :id"""
                ),
                {"id": organization_id},
            )
        ).first()
        if row is None:
            return None
        return OrganizationSettings(
            row.name, row.tolerance_min_cents, row.tolerance_bp, tuple(row.detraction_rates_bp)
        )

    async def update_organization_settings(
        self, organization_id: UUID, settings: OrganizationSettings
    ) -> None:
        await self._execute(
            """UPDATE organizations
               SET name = :name, tolerance_min_cents = :minimum, tolerance_bp = :bp,
                   detraction_rates_bp = :rates
               WHERE id = :id""",
            name=settings.name,
            minimum=settings.tolerance_min_cents,
            bp=settings.tolerance_bp,
            rates=list(settings.detraction_rates_bp),
            id=organization_id,
        )

    async def insert_organization(
        self,
        organization_id: UUID,
        name: str,
        now: datetime,
        *,
        demo_expires_at: datetime | None = None,
    ) -> None:
        try:
            await self._execute(
                """INSERT INTO organizations (id, name, is_demo, demo_expires_at, created_at)
                   VALUES (:id, :name, :is_demo, :expires, :now)""",
                id=organization_id,
                name=name,
                is_demo=demo_expires_at is not None,
                expires=demo_expires_at,
                now=now,
            )
        except IntegrityError as error:
            raise IdConflictError from error

    async def is_admin(self, organization_id: UUID, user_id: UUID) -> bool:
        result = await self._connection.execute(
            text(
                """SELECT 1 FROM member_roles r
                   JOIN memberships m USING (organization_id, user_id)
                   WHERE r.organization_id = :org AND r.user_id = :user AND r.role = 'admin'
                     AND m.removed_at IS NULL"""
            ),
            {"org": organization_id, "user": user_id},
        )
        return result.first() is not None

    async def insert_membership(
        self, organization_id: UUID, user_id: UUID, roles: frozenset[Role], now: datetime
    ) -> None:
        await self._execute(
            """INSERT INTO memberships (organization_id, user_id, created_at)
               VALUES (:organization_id, :user_id, :now)""",
            organization_id=organization_id,
            user_id=user_id,
            now=now,
        )
        for role in sorted(roles):
            await self._execute(
                """INSERT INTO member_roles (organization_id, user_id, role)
                   VALUES (:organization_id, :user_id, :role)""",
                organization_id=organization_id,
                user_id=user_id,
                role=role.value,
            )

    async def user_organizations(self, user_id: UUID) -> list[OrganizationAccess]:
        rows = await self._connection.execute(
            text("SELECT * FROM app_user_orgs(:user_id)"), {"user_id": user_id}
        )
        return [
            OrganizationAccess(
                row.organization_id, row.name, row.is_demo, frozenset(Role(r) for r in row.roles)
            )
            for row in rows
        ]

    async def insert_session(self, session: Session, token_hash: str) -> None:
        await self._execute(
            """INSERT INTO sessions (id, user_id, organization_id, token_hash, created_at,
                                     last_seen_at, expires_at)
               VALUES (:id, :user_id, :organization_id, :token_hash, :created_at,
                       :last_seen_at, :expires_at)""",
            id=session.id,
            user_id=session.user_id,
            organization_id=session.organization_id,
            token_hash=token_hash,
            created_at=session.created_at,
            last_seen_at=session.last_seen_at,
            expires_at=session.expires_at,
        )

    async def find_session(self, token_hash: str) -> Session | None:
        row = (
            await self._connection.execute(
                text(
                    """SELECT id, user_id, organization_id, created_at, last_seen_at, expires_at,
                              revoked_at
                       FROM sessions WHERE token_hash = :token_hash"""
                ),
                {"token_hash": token_hash},
            )
        ).first()
        if row is None:
            return None
        return Session(
            row.id,
            row.user_id,
            row.organization_id,
            row.created_at,
            row.last_seen_at,
            row.expires_at,
            row.revoked_at,
        )

    async def touch_session(self, session_id: UUID, now: datetime) -> None:
        await self._execute(
            "UPDATE sessions SET last_seen_at = :now WHERE id = :id", now=now, id=session_id
        )

    async def revoke_session(self, session_id: UUID, now: datetime) -> None:
        await self._execute(
            "UPDATE sessions SET revoked_at = :now WHERE id = :id AND revoked_at IS NULL",
            now=now,
            id=session_id,
        )


class SqlIdentityTransactions:
    def __init__(self, engine: AsyncEngine, audit_factory: AuditRecorderFactory) -> None:
        self._engine = engine
        self._audit_factory = audit_factory

    @asynccontextmanager
    async def anonymous(self) -> AsyncIterator[SqlIdentityStore]:
        async with anonymous_transaction(self._engine) as connection:
            yield SqlIdentityStore(connection, self._audit_factory(connection))

    @asynccontextmanager
    async def organization(self, organization_id: UUID) -> AsyncIterator[SqlIdentityStore]:
        async with organization_transaction(self._engine, organization_id) as connection:
            yield SqlIdentityStore(connection, self._audit_factory(connection))


class SqlRateLimiter:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def hit(self, key: str, window: timedelta, now: datetime) -> int:
        epoch = datetime(1970, 1, 1, tzinfo=now.tzinfo)
        window_start = epoch + (now - epoch) // window * window
        async with anonymous_transaction(self._engine) as connection:
            result = await connection.execute(
                text(
                    """INSERT INTO rate_limits (key_hash, window_start, count)
                       VALUES (:key, :window_start, 1)
                       ON CONFLICT (key_hash, window_start)
                       DO UPDATE SET count = rate_limits.count + 1
                       RETURNING count"""
                ),
                {"key": key, "window_start": window_start},
            )
            count: int = result.scalar_one()
            return count
