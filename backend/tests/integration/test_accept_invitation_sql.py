from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from concilia.shared.infrastructure.db import anonymous_transaction, organization_transaction

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 11, 16, 15, 0, tzinfo=UTC)


def _email() -> str:
    return f"{uuid7()}@example.test"


async def _organization(owner_engine: AsyncEngine) -> tuple[UUID, UUID]:
    organization_id, admin_id = uuid7(), uuid7()
    async with owner_engine.begin() as connection:
        for sql in (
            "INSERT INTO organizations (id, name, created_at) VALUES (:org, 'Andina', :now)",
            """INSERT INTO users (id, email, password_hash, display_name, created_at)
               VALUES (:admin, :admin_email, 'x', 'Admin', :now)""",
            """INSERT INTO memberships (organization_id, user_id, created_at)
               VALUES (:org, :admin, :now)""",
            """INSERT INTO member_roles (organization_id, user_id, role)
               VALUES (:org, :admin, 'admin')""",
        ):
            await connection.execute(
                text(sql),
                {
                    "org": organization_id,
                    "admin": admin_id,
                    "admin_email": f"{admin_id}@example.test",
                    "now": NOW,
                },
            )
    return organization_id, admin_id


async def _user(owner_engine: AsyncEngine, email: str) -> UUID:
    user_id = uuid7()
    async with owner_engine.begin() as connection:
        await connection.execute(
            text(
                """INSERT INTO users (id, email, password_hash, display_name, created_at)
                   VALUES (:id, :email, 'x', 'Invitee', :now)"""
            ),
            {"id": user_id, "email": email, "now": NOW},
        )
    return user_id


async def _invite(
    owner_engine: AsyncEngine,
    organization_id: UUID,
    admin_id: UUID,
    email: str,
    roles: list[str],
    *,
    expires_at: datetime = NOW + timedelta(days=7),
    revoked: bool = False,
) -> str:
    token_hash = f"hash-{uuid7()}"
    async with owner_engine.begin() as connection:
        await connection.execute(
            text(
                """INSERT INTO invitations (id, organization_id, email, roles, token_hash,
                                           created_by, created_at, expires_at, revoked_at)
                   VALUES (:id, :org, :email, :roles, :hash, :admin, :created, :expires,
                           :revoked)"""
            ),
            {
                "id": uuid7(),
                "org": organization_id,
                "email": email,
                "roles": roles,
                "hash": token_hash,
                "admin": admin_id,
                "created": NOW - timedelta(days=1),
                "expires": expires_at,
                "revoked": NOW if revoked else None,
            },
        )
    return token_hash


async def _accept(app_engine: AsyncEngine, token_hash: str, user_id: UUID) -> UUID:
    async with anonymous_transaction(app_engine) as connection:
        result = await connection.execute(
            text("SELECT app_accept_invitation(:hash, :user, :now, :event)"),
            {"hash": token_hash, "user": user_id, "now": NOW, "event": uuid7()},
        )
        return UUID(str(result.scalar_one()))


async def _roles(app_engine: AsyncEngine, organization_id: UUID, user_id: UUID) -> set[str]:
    async with organization_transaction(app_engine, organization_id) as connection:
        rows = await connection.execute(
            text(
                """SELECT r.role FROM member_roles r
                   JOIN memberships m USING (organization_id, user_id)
                   WHERE r.user_id = :user AND m.removed_at IS NULL"""
            ),
            {"user": user_id},
        )
        return set(rows.scalars())


async def test_accepting_creates_the_membership_with_the_invited_roles(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    organization_id, admin_id = await _organization(owner_engine)
    email = _email()
    user_id = await _user(owner_engine, email)
    token_hash = await _invite(
        owner_engine, organization_id, admin_id, email, ["analyst", "reviewer"]
    )

    assert await _accept(app_engine, token_hash, user_id) == organization_id

    assert await _roles(app_engine, organization_id, user_id) == {"analyst", "reviewer"}
    async with organization_transaction(app_engine, organization_id) as connection:
        accepted_at = await connection.scalar(
            text("SELECT accepted_at FROM invitations WHERE token_hash = :hash"),
            {"hash": token_hash},
        )
        event = (
            await connection.execute(
                text(
                    """SELECT action, actor_user_id, metadata FROM audit_events
                       WHERE action = 'invitation.accepted'"""
                )
            )
        ).one()
    assert accepted_at == NOW
    assert event.action == "invitation.accepted"
    assert event.actor_user_id == user_id
    assert dict(event.metadata) == {"roles": ["analyst", "reviewer"]}


async def test_a_removed_member_comes_back_with_only_the_new_roles(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    organization_id, admin_id = await _organization(owner_engine)
    email = _email()
    user_id = await _user(owner_engine, email)
    first = await _invite(owner_engine, organization_id, admin_id, email, ["admin"])
    await _accept(app_engine, first, user_id)
    async with organization_transaction(app_engine, organization_id) as connection:
        await connection.execute(
            text("UPDATE memberships SET removed_at = :now WHERE user_id = :user"),
            {"now": NOW, "user": user_id},
        )
        await connection.execute(
            text("DELETE FROM member_roles WHERE user_id = :user"), {"user": user_id}
        )

    second = await _invite(owner_engine, organization_id, admin_id, email, ["analyst"])
    await _accept(app_engine, second, user_id)

    assert await _roles(app_engine, organization_id, user_id) == {"analyst"}


@pytest.mark.parametrize(
    "case", ["accepted", "expired", "revoked", "other_email", "active_member", "unknown"]
)
async def test_an_invitation_that_cannot_be_used_is_rejected(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, case: str
) -> None:
    organization_id, admin_id = await _organization(owner_engine)
    own_email = _email()
    user_id = await _user(owner_engine, own_email)
    email = _email() if case == "other_email" else own_email
    token_hash = await _invite(
        owner_engine,
        organization_id,
        admin_id,
        email,
        ["analyst"],
        expires_at=NOW if case == "expired" else NOW + timedelta(days=7),
        revoked=case == "revoked",
    )
    if case == "accepted":
        await _accept(app_engine, token_hash, user_id)
    if case == "active_member":
        again = await _invite(owner_engine, organization_id, admin_id, email, ["reviewer"])
        await _accept(app_engine, again, user_id)
    if case == "unknown":
        token_hash = "no-such-hash"

    with pytest.raises(DBAPIError, match="invitation_not_valid"):
        await _accept(app_engine, token_hash, user_id)
