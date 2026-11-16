from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.support.api import ORIGIN, build_app, xsrf_header
from tests.support.clock import FixedClock
from tests.support.database import DatabaseUrls
from tests.support.imports import NOW, client_id, statement_setup

pytestmark = pytest.mark.anyio


@pytest.fixture
async def app(database: DatabaseUrls) -> AsyncIterator[FastAPI]:
    app = build_app(database.for_role("concilia_app"), FixedClock(NOW), demo_ttl_hours=4)
    yield app
    await app.state.engine.dispose()


async def _tenant_tables(owner_engine: AsyncEngine) -> list[str]:
    async with owner_engine.connect() as connection:
        return list(
            await connection.scalars(
                text(
                    """SELECT c.table_name FROM information_schema.columns c
                       JOIN information_schema.tables t
                         ON t.table_name = c.table_name AND t.table_schema = c.table_schema
                       WHERE c.table_schema = 'public' AND c.column_name = 'organization_id'
                         AND t.table_type = 'BASE TABLE'
                       ORDER BY c.table_name"""
                )
            )
        )


async def _rows_of(owner_engine: AsyncEngine, organization_id: UUID) -> dict[str, int]:
    counts = {}
    async with owner_engine.connect() as connection:
        for table in await _tenant_tables(owner_engine):
            counts[table] = await connection.scalar(
                text(f"SELECT count(*) FROM {table} WHERE organization_id = :id"),
                {"id": organization_id},
            )
        counts["organizations"] = await connection.scalar(
            text("SELECT count(*) FROM organizations WHERE id = :id"), {"id": organization_id}
        )
    return counts


async def _cleanup(worker_engine: AsyncEngine, at: timedelta) -> None:
    async with worker_engine.begin() as connection:
        await connection.execute(text("SELECT app_cleanup(:now)"), {"now": NOW + at})


async def test_an_expired_demo_is_deleted_entirely_and_nothing_else(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine
) -> None:
    real = await statement_setup(owner_engine)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as visitor:
        demo = UUID((await visitor.post("/api/public/demo")).json()["organization_id"])
        [account] = (await visitor.get("/api/app/bank-accounts")).json()
        await visitor.post(
            "/api/app/engine-runs",
            json={"id": client_id(), "bank_account_id": account["id"], "period": "2026-11-01"},
            headers=xsrf_header(visitor),
        )
        await visitor.post(
            "/api/app/demo/switch-role", json={"role": "reviewer"}, headers=xsrf_header(visitor)
        )
        async with owner_engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO match_decisions (id, organization_id, match_id, action,
                                                    decided_by, decided_at)
                       SELECT gen_random_uuid(), organization_id, id, 'confirm',
                              (SELECT user_id FROM member_roles
                               WHERE organization_id = :org AND role = 'analyst'), :now
                       FROM matches WHERE organization_id = :org AND rule = 'R1' LIMIT 1"""
                ),
                {"org": demo, "now": NOW},
            )
        demo_users = await _demo_users(owner_engine, demo)
        before = await _rows_of(owner_engine, demo)
        real_before = await _rows_of(owner_engine, real.organization_id)

        await _cleanup(worker_engine, timedelta(hours=3))
        kept = await _rows_of(owner_engine, demo)
        await _cleanup(worker_engine, timedelta(hours=4))
        after = await _rows_of(owner_engine, demo)
        session = await visitor.get("/api/app/session")

    assert kept == before
    assert {table for table, count in before.items() if count} >= {
        "organizations",
        "memberships",
        "bank_movements",
        "receivables",
        "matches",
        "match_items",
        "match_decisions",
        "engine_runs",
        "jobs",
        "audit_events",
    }
    assert set(after.values()) == {0}
    assert await _rows_of(owner_engine, real.organization_id) == real_before
    assert session.status_code == 401
    async with owner_engine.connect() as connection:
        leftovers = await connection.scalar(
            text(
                """SELECT (SELECT count(*) FROM users WHERE id = ANY(:users))
                        + (SELECT count(*) FROM sessions WHERE user_id = ANY(:users))"""
            ),
            {"users": demo_users},
        )
    assert len(demo_users) == 3
    assert leftovers == 0


async def _demo_users(owner_engine: AsyncEngine, organization_id: UUID) -> list[UUID]:
    async with owner_engine.connect() as connection:
        return list(
            await connection.scalars(
                text("SELECT user_id FROM memberships WHERE organization_id = :id"),
                {"id": organization_id},
            )
        )


async def test_a_local_demo_never_expires(
    database: DatabaseUrls, owner_engine: AsyncEngine, worker_engine: AsyncEngine
) -> None:
    app = build_app(database.for_role("concilia_app"), FixedClock(NOW))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as visitor:
        demo = UUID((await visitor.post("/api/public/demo")).json()["organization_id"])
    await app.state.engine.dispose()

    await _cleanup(worker_engine, timedelta(days=3650))

    assert (await _rows_of(owner_engine, demo))["organizations"] == 1


async def test_only_the_cleanup_can_reset_a_demo(
    app_engine: AsyncEngine, worker_engine: AsyncEngine
) -> None:
    for engine in (app_engine, worker_engine):
        with pytest.raises(Exception, match="permission denied"):
            async with engine.begin() as connection:
                await connection.execute(text("SELECT app_reset_demo(gen_random_uuid())"))
