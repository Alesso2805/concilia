from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid7

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from concilia.shared.infrastructure.db import anonymous_transaction, organization_transaction

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 11, 16, 15, 0, tzinfo=UTC)
RLS_TABLES = (
    "organizations",
    "memberships",
    "member_roles",
    "invitations",
    "audit_events",
    "jobs",
)


@dataclass(frozen=True)
class Tenant:
    organization_id: UUID
    user_id: UUID


async def _create_tenant(owner_engine: AsyncEngine, name: str) -> Tenant:
    tenant = Tenant(uuid7(), uuid7())
    params = {
        "org": tenant.organization_id,
        "user": tenant.user_id,
        "name": name,
        "email": f"{tenant.user_id}@example.test",
        "now": NOW,
    }
    async with owner_engine.begin() as connection:
        for sql in (
            "INSERT INTO organizations (id, name, created_at) VALUES (:org, :name, :now)",
            """INSERT INTO users (id, email, password_hash, display_name, created_at)
               VALUES (:user, :email, 'x', :name, :now)""",
            """INSERT INTO memberships (organization_id, user_id, created_at)
               VALUES (:org, :user, :now)""",
            """INSERT INTO member_roles (organization_id, user_id, role)
               VALUES (:org, :user, 'admin')""",
            """INSERT INTO invitations (id, organization_id, email, roles, token_hash, created_by,
                                        created_at, expires_at)
               VALUES (gen_random_uuid(), :org, 'invitee@example.test', '{analyst}',
                       gen_random_uuid()::text, :user, :now,
                       CAST(:now AS timestamptz) + interval '7 days')""",
            """INSERT INTO audit_events (id, organization_id, actor_user_id, action, entity, at)
               VALUES (gen_random_uuid(), :org, :user, 'test.created', 'organization', :now)""",
            """INSERT INTO jobs (id, organization_id, kind, run_after, created_at)
               VALUES (gen_random_uuid(), :org, 'run_engine', :now, :now)""",
        ):
            await connection.execute(text(sql), params)
    return tenant


@pytest.fixture
async def tenants(owner_engine: AsyncEngine) -> tuple[Tenant, Tenant]:
    return await _create_tenant(owner_engine, "alpha"), await _create_tenant(owner_engine, "beta")


async def _visible_organizations(engine: AsyncEngine, table: str, org: UUID | None) -> set[UUID]:
    column = "id" if table == "organizations" else "organization_id"
    sql = text(f"SELECT DISTINCT {column} FROM {table}")
    if org is None:
        async with anonymous_transaction(engine) as connection:
            return set((await connection.execute(sql)).scalars())
    async with organization_transaction(engine, org) as connection:
        return set((await connection.execute(sql)).scalars())


@pytest.mark.parametrize("table", RLS_TABLES)
async def test_app_sees_only_its_organization(
    app_engine: AsyncEngine, tenants: tuple[Tenant, Tenant], table: str
) -> None:
    alpha, beta = tenants

    assert await _visible_organizations(app_engine, table, alpha.organization_id) == {
        alpha.organization_id
    }
    assert await _visible_organizations(app_engine, table, beta.organization_id) == {
        beta.organization_id
    }


@pytest.mark.parametrize("table", RLS_TABLES)
async def test_without_organization_context_nothing_is_visible(
    app_engine: AsyncEngine, tenants: tuple[Tenant, Tenant], table: str
) -> None:
    assert await _visible_organizations(app_engine, table, None) == set()


async def test_app_cannot_write_into_another_organization(
    app_engine: AsyncEngine, tenants: tuple[Tenant, Tenant]
) -> None:
    alpha, beta = tenants

    with pytest.raises(DBAPIError, match="row-level security"):
        async with organization_transaction(app_engine, alpha.organization_id) as connection:
            await connection.execute(
                text(
                    """INSERT INTO audit_events (id, organization_id, action, entity, at)
                       VALUES (:id, :org, 'test.created', 'organization', :now)"""
                ),
                {"id": uuid7(), "org": beta.organization_id, "now": NOW},
            )


async def test_worker_sees_jobs_of_every_organization(
    worker_engine: AsyncEngine, tenants: tuple[Tenant, Tenant]
) -> None:
    alpha, beta = tenants

    visible = await _visible_organizations(worker_engine, "jobs", None)

    assert {alpha.organization_id, beta.organization_id} <= visible


async def test_worker_sees_other_tables_only_in_its_job_organization(
    worker_engine: AsyncEngine, tenants: tuple[Tenant, Tenant]
) -> None:
    alpha, _ = tenants

    assert await _visible_organizations(worker_engine, "audit_events", alpha.organization_id) == {
        alpha.organization_id
    }
