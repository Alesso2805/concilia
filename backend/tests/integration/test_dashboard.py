from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.support.api import Member, add_member, build_app, signed_in, xsrf_header
from tests.support.clock import FixedClock
from tests.support.database import DatabaseUrls
from tests.support.imports import (
    NOW,
    RECEIVABLES,
    STATEMENT,
    Setup,
    client_id,
    receivables_profile,
    statement_setup,
    upload,
    work,
)

pytestmark = pytest.mark.anyio

IN_MARCH = datetime(2027, 3, 10, 15, 0, tzinfo=UTC)
ZERO = {"count": 0, "cents": 0}


@pytest.fixture
async def app(database: DatabaseUrls) -> AsyncIterator[FastAPI]:
    app = build_app(database.for_role("concilia_app"), FixedClock(NOW))
    yield app
    await app.state.engine.dispose()


@pytest.fixture
async def march_app(database: DatabaseUrls) -> AsyncIterator[FastAPI]:
    app = build_app(database.for_role("concilia_app"), FixedClock(IN_MARCH))
    yield app
    await app.state.engine.dispose()


async def _post(client: httpx.AsyncClient, path: str, body: dict[str, Any]) -> httpx.Response:
    return await client.post(path, json={"id": client_id(), **body}, headers=xsrf_header(client))


@pytest.fixture
async def books(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine
) -> tuple[Setup, Member]:
    """January approved by the engine's proposal; February confirmed by hand with a 5.00
    commission."""
    clock = FixedClock(NOW)
    setup = await statement_setup(owner_engine)
    reviewer = await add_member(owner_engine, NOW, setup.organization_id, ["reviewer"])
    profile_id = await receivables_profile(owner_engine, setup)
    account = str(setup.account_id)
    async with signed_in(app, setup.member.email) as analyst:
        for content, profile in ((STATEMENT, None), (RECEIVABLES, profile_id)):
            file_id = (await upload(analyst, setup, content, profile_id=profile)).json()["file"][
                "id"
            ]
            await work(worker_engine, clock)
            await analyst.post(f"/api/app/imports/{file_id}/confirm", headers=xsrf_header(analyst))
            await work(worker_engine, clock)
        await _post(
            analyst, "/api/app/engine-runs", {"bank_account_id": account, "period": "2027-01-01"}
        )
        await work(worker_engine, clock)
        [match] = (
            await analyst.get(
                "/api/app/matches", params={"bank_account_id": account, "period": "2027-01-01"}
            )
        ).json()["matches"]
        await _post(analyst, f"/api/app/matches/{match['id']}/decisions", {"action": "confirm"})
        [credit] = (
            await analyst.get(
                "/api/app/inbox/credits",
                params={"bank_account_id": account, "period": "2027-02-01"},
            )
        ).json()["credits"]
        [receivable] = (
            await analyst.get("/api/app/inbox/receivables", params={"q": "F001-124"})
        ).json()["receivables"]
        manual = await _post(
            analyst,
            "/api/app/matches",
            {
                "bank_account_id": account,
                "credit_ids": [credit["id"]],
                "applications": [{"receivable_id": receivable["id"], "applied_cents": 49_500}],
                "difference_reason": "commission",
            },
        )
        assert manual.status_code == 201
    async with signed_in(app, reviewer.email) as client:
        await _post(client, f"/api/app/matches/{match['id']}/decisions", {"action": "approve"})
    return setup, reviewer


async def _dashboard(app: FastAPI, member: Member, setup: Setup, period: str) -> httpx.Response:
    async with signed_in(app, member.email) as client:
        return await client.get(
            "/api/app/reports/dashboard",
            params={"bank_account_id": str(setup.account_id), "period": period},
        )


async def test_a_past_month_counts_its_credits_by_status_and_its_differences(
    march_app: FastAPI, books: tuple[Setup, Member]
) -> None:
    setup, reviewer = books

    january = (await _dashboard(march_app, reviewer, setup, "2027-01-01")).json()
    february = (await _dashboard(march_app, setup.member, setup, "2027-02-01")).json()

    assert january["reference_date"] == "2027-01-31"
    assert january["credits"] == {
        "free": ZERO,
        "proposed": ZERO,
        "confirmed": ZERO,
        "approved": {"count": 1, "cents": 118_000},
    }
    assert [age["count"] for age in january["pending"]] == [0, 0, 0]
    assert january["differences"] == []
    assert february["reference_date"] == "2027-02-28"
    assert february["credits"]["confirmed"] == {"count": 1, "cents": 50_000}
    assert february["pending"] == [
        {"bucket": "0-7", **ZERO},
        {"bucket": "8-30", "count": 1, "cents": 50_000},
        {"bucket": "31+", **ZERO},
    ]
    assert february["differences"] == [{"reason": "commission", "count": 1, "cents": 500}]


async def test_pending_credits_of_earlier_months_age_against_today_in_the_current_month(
    march_app: FastAPI, books: tuple[Setup, Member]
) -> None:
    setup, reviewer = books

    march = (await _dashboard(march_app, reviewer, setup, "2027-03-01")).json()

    assert march["reference_date"] == "2027-03-10"
    assert march["credits"] == dict.fromkeys(("free", "proposed", "confirmed", "approved"), ZERO)
    assert march["pending"][2] == {"bucket": "31+", "count": 1, "cents": 50_000}
    assert march["closed"] is False


async def test_the_dashboard_stays_inside_its_organization(
    app: FastAPI, owner_engine: AsyncEngine, books: tuple[Setup, Member]
) -> None:
    setup, _ = books
    stranger = await statement_setup(owner_engine, ["reviewer"])

    foreign = await _dashboard(app, stranger.member, setup, "2027-01-01")
    own = await _dashboard(app, stranger.member, stranger, "2027-01-01")

    assert (foreign.status_code, foreign.json()["detail"]) == (404, "not_found")
    assert own.json()["credits"]["free"] == ZERO


async def test_a_period_is_the_first_day_of_a_month(
    app: FastAPI, books: tuple[Setup, Member]
) -> None:
    setup, reviewer = books

    response = await _dashboard(app, reviewer, setup, "2027-01-15")

    assert (response.status_code, response.json()["detail"]) == (422, "invalid_period")
