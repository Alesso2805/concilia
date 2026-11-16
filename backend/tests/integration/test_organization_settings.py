from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.support.api import Member, add_member, build_app, create_member, signed_in, xsrf_header
from tests.support.clock import FixedClock
from tests.support.database import DatabaseUrls

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 11, 23, 14, 0, tzinfo=UTC)
DEFAULTS = {
    "name": "Andina",
    "tolerance_min_cents": 100,
    "tolerance_bp": 50,
    "detraction_rates_bp": [1000, 1200],
}


@pytest.fixture
async def app(database: DatabaseUrls) -> AsyncIterator[FastAPI]:
    app = build_app(database.for_role("concilia_app"), FixedClock(NOW))
    yield app
    await app.state.engine.dispose()


@pytest.fixture
async def admin(owner_engine: AsyncEngine) -> Member:
    return await create_member(owner_engine, NOW, organizations={"Andina": ["admin"]})


async def _put(client: httpx.AsyncClient, body: dict[str, Any]) -> httpx.Response:
    return await client.put("/api/app/organization", json=body, headers=xsrf_header(client))


async def _settings_events(owner_engine: AsyncEngine, member: Member) -> list[Any]:
    async with owner_engine.connect() as connection:
        rows = await connection.execute(
            text(
                """SELECT metadata FROM audit_events
                   WHERE organization_id = :org AND action = 'organization.settings_changed'"""
            ),
            {"org": member.organization_ids[0]},
        )
        return [dict(row.metadata) for row in rows]


async def test_members_read_the_defaults_and_admins_change_them(
    app: FastAPI, admin: Member, owner_engine: AsyncEngine
) -> None:
    analyst = await add_member(owner_engine, NOW, admin.organization_ids[0], ["analyst"])
    other = await create_member(owner_engine, NOW, organizations={"Beta": ["admin"]})
    wanted = {**DEFAULTS, "tolerance_bp": 25, "detraction_rates_bp": [1200, 400]}
    async with signed_in(app, analyst.email) as client:
        defaults = (await client.get("/api/app/organization")).json()
        forbidden = await _put(client, wanted)
    async with signed_in(app, admin.email) as client:
        changed = await _put(client, wanted)
        unchanged = await _put(client, wanted)
        after = (await client.get("/api/app/organization")).json()
    async with signed_in(app, other.email) as client:
        elsewhere = (await client.get("/api/app/organization")).json()

    assert defaults == DEFAULTS
    assert (forbidden.status_code, forbidden.json()["detail"]) == (403, "role_required")
    assert (changed.status_code, unchanged.status_code) == (204, 204)
    assert after == {**wanted, "detraction_rates_bp": [400, 1200]}
    assert elsewhere == {**DEFAULTS, "name": "Beta"}
    assert await _settings_events(owner_engine, admin) == [
        {"fields": ["tolerance_bp", "detraction_rates_bp"]}
    ]


@pytest.mark.parametrize(
    "changes",
    [
        {"detraction_rates_bp": [1000, 1000]},
        {"detraction_rates_bp": [0]},
        {"tolerance_bp": 10_001},
        {"tolerance_min_cents": -1},
        {"name": "   "},
        {"detraction_rates_bp": [100, 200, 300, 400, 500, 600]},
    ],
)
async def test_invalid_settings_are_rejected(
    app: FastAPI, admin: Member, changes: dict[str, Any]
) -> None:
    async with signed_in(app, admin.email) as client:
        response = await _put(client, {**DEFAULTS, **changes})

    assert response.status_code == 422
