from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.support.api import Member, build_app, signed_in
from tests.support.clock import FixedClock
from tests.support.database import DatabaseUrls
from tests.support.imports import NOW, Setup, statement_setup
from tests.support.reporting import reconciled_books

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


@pytest.fixture
async def books(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine
) -> tuple[Setup, Member]:
    return await reconciled_books(app, owner_engine, worker_engine)


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
