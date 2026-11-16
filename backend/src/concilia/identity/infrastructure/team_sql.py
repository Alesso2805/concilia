from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from concilia.identity.domain.model import Role
from concilia.identity.domain.team import Invitation, Member
from concilia.identity.infrastructure.sql import AuditRecorderFactory, SqlIdentityStore
from concilia.shared.infrastructure.db import anonymous_transaction, organization_transaction
from concilia.shared.kernel.ids import IdConflictError

INVITATION_COLUMNS = """id, organization_id, email, roles, created_by, created_at, expires_at,
                        accepted_at, revoked_at"""


def _invitation(row: Any) -> Invitation:
    return Invitation(
        row.id,
        row.organization_id,
        row.email,
        frozenset(Role(role) for role in row.roles),
        row.created_by,
        row.created_at,
        row.expires_at,
        row.accepted_at,
        row.revoked_at,
    )


class SqlTeamStore(SqlIdentityStore):
    async def members(self) -> list[Member]:
        rows = await self._connection.execute(
            text(
                """SELECT m.user_id, u.display_name, lower(u.email) AS email, m.created_at,
                          coalesce(array_agg(r.role) FILTER (WHERE r.role IS NOT NULL), '{}')
                              AS roles
                   FROM memberships m
                   JOIN users u ON u.id = m.user_id
                   LEFT JOIN member_roles r
                       ON r.organization_id = m.organization_id AND r.user_id = m.user_id
                   WHERE m.removed_at IS NULL
                   GROUP BY m.user_id, u.display_name, u.email, m.created_at
                   ORDER BY u.display_name, m.user_id"""
            )
        )
        return [
            Member(
                row.user_id,
                row.display_name,
                row.email,
                frozenset(Role(role) for role in row.roles),
                row.created_at,
            )
            for row in rows
        ]

    async def invitations(self) -> list[Invitation]:
        rows = await self._connection.execute(
            text(
                f"SELECT {INVITATION_COLUMNS} FROM invitations ORDER BY created_at DESC, id"  # noqa: S608
            )
        )
        return [_invitation(row) for row in rows]

    async def find_invitation(self, invitation_id: UUID) -> Invitation | None:
        row = (
            await self._connection.execute(
                text(f"SELECT {INVITATION_COLUMNS} FROM invitations WHERE id = :id"),  # noqa: S608
                {"id": invitation_id},
            )
        ).first()
        return None if row is None else _invitation(row)

    async def insert_invitation(self, invitation: Invitation, token_hash: str) -> None:
        try:
            await self._execute(
                """INSERT INTO invitations (id, organization_id, email, roles, token_hash,
                                            created_by, created_at, expires_at)
                   VALUES (:id, :organization_id, :email, :roles, :token_hash, :created_by,
                           :created_at, :expires_at)""",
                id=invitation.id,
                organization_id=invitation.organization_id,
                email=invitation.email,
                roles=sorted(role.value for role in invitation.roles),
                token_hash=token_hash,
                created_by=invitation.created_by,
                created_at=invitation.created_at,
                expires_at=invitation.expires_at,
            )
        except IntegrityError as error:
            raise IdConflictError from error

    async def revoke_invitation(self, invitation_id: UUID, now: datetime) -> None:
        await self._execute(
            "UPDATE invitations SET revoked_at = :now WHERE id = :id", now=now, id=invitation_id
        )

    async def replace_roles(
        self, organization_id: UUID, user_id: UUID, roles: frozenset[Role]
    ) -> None:
        await self._execute(
            "DELETE FROM member_roles WHERE organization_id = :org AND user_id = :user",
            org=organization_id,
            user=user_id,
        )
        for role in sorted(roles):
            await self._execute(
                """INSERT INTO member_roles (organization_id, user_id, role)
                   VALUES (:org, :user, :role)""",
                org=organization_id,
                user=user_id,
                role=role.value,
            )

    async def remove_member(self, organization_id: UUID, user_id: UUID, now: datetime) -> None:
        await self._execute(
            "DELETE FROM member_roles WHERE organization_id = :org AND user_id = :user",
            org=organization_id,
            user=user_id,
        )
        await self._execute(
            """UPDATE memberships SET removed_at = :now
               WHERE organization_id = :org AND user_id = :user""",
            now=now,
            org=organization_id,
            user=user_id,
        )

    async def revoke_sessions(self, organization_id: UUID, user_id: UUID, now: datetime) -> None:
        await self._execute(
            """UPDATE sessions SET revoked_at = :now
               WHERE organization_id = :org AND user_id = :user AND revoked_at IS NULL""",
            now=now,
            org=organization_id,
            user=user_id,
        )

    async def accept_invitation(
        self, token_hash: str, user_id: UUID, now: datetime, event_id: UUID
    ) -> UUID | None:
        try:
            async with self._connection.begin_nested():
                result = await self._connection.execute(
                    text("SELECT app_accept_invitation(:hash, :user, :now, :event)"),
                    {"hash": token_hash, "user": user_id, "now": now, "event": event_id},
                )
                return UUID(str(result.scalar_one()))
        except DBAPIError as error:
            if "invitation_not_valid" in str(error.orig):
                return None
            raise


class SqlTeamTransactions:
    def __init__(self, engine: AsyncEngine, audit_factory: AuditRecorderFactory) -> None:
        self._engine = engine
        self._audit_factory = audit_factory

    @asynccontextmanager
    async def anonymous(self) -> AsyncIterator[SqlTeamStore]:
        async with anonymous_transaction(self._engine) as connection:
            yield SqlTeamStore(connection, self._audit_factory(connection))

    @asynccontextmanager
    async def organization(self, organization_id: UUID) -> AsyncIterator[SqlTeamStore]:
        async with organization_transaction(self._engine, organization_id) as connection:
            yield SqlTeamStore(connection, self._audit_factory(connection))
