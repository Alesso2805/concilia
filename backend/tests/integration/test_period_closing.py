import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
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

JANUARY = "2027-01-01"


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
async def app(database: DatabaseUrls, clock: FixedClock) -> AsyncIterator[FastAPI]:
    app = build_app(database.for_role("concilia_app"), clock)
    yield app
    await app.state.engine.dispose()


@dataclass(frozen=True)
class Books:
    setup: Setup
    reviewer: Member
    other_reviewer: Member

    @property
    def analyst(self) -> Member:
        return self.setup.member


@pytest.fixture
async def books(owner_engine: AsyncEngine) -> Books:
    setup = await statement_setup(owner_engine)
    return Books(
        setup,
        await add_member(owner_engine, NOW, setup.organization_id, ["reviewer"]),
        await add_member(owner_engine, NOW, setup.organization_id, ["reviewer"]),
    )


async def _with_proposals(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, books: Books
) -> str:
    """Imports January and runs the engine on it; returns its single proposal."""
    clock = FixedClock(NOW)
    profile_id = await receivables_profile(owner_engine, books.setup)
    async with signed_in(app, books.analyst.email) as client:
        for content, profile in ((STATEMENT, None), (RECEIVABLES, profile_id)):
            response = await upload(client, books.setup, content, profile_id=profile)
            await work(worker_engine, clock)
            file_id = response.json()["file"]["id"]
            await client.post(f"/api/app/imports/{file_id}/confirm", headers=xsrf_header(client))
            await work(worker_engine, clock)
        await _run_engine(client, books.setup)
        await work(worker_engine, clock)
        matches = await client.get(
            "/api/app/matches",
            params={"bank_account_id": str(books.setup.account_id), "period": JANUARY},
        )
    [match] = matches.json()["matches"]
    return str(match["id"])


async def _run_engine(client: httpx.AsyncClient, setup: Setup) -> httpx.Response:
    return await client.post(
        "/api/app/engine-runs",
        json={"id": client_id(), "bank_account_id": str(setup.account_id), "period": JANUARY},
        headers=xsrf_header(client),
    )


async def _period(
    client: httpx.AsyncClient,
    setup: Setup,
    action: str,
    period: str = JANUARY,
    **fields: Any,
) -> httpx.Response:
    return await client.post(
        "/api/app/period-events",
        json={
            "id": fields.pop("id", None) or client_id(),
            "bank_account_id": str(fields.pop("account", setup.account_id)),
            "period": period,
            "action": action,
            **fields,
        },
        headers=xsrf_header(client),
    )


async def _decide(client: httpx.AsyncClient, match_id: str, action: str, **fields: Any) -> Any:
    return await client.post(
        f"/api/app/matches/{match_id}/decisions",
        json={"id": client_id(), "action": action, **fields},
        headers=xsrf_header(client),
    )


async def _closed(client: httpx.AsyncClient, setup: Setup) -> dict[str, bool]:
    response = await client.get(
        "/api/app/inbox/periods", params={"bank_account_id": str(setup.account_id)}
    )
    return {period["period"]: period["closed"] for period in response.json()}


async def test_a_reviewer_closes_a_month_once_nothing_is_pending_and_reopens_it(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, books: Books
) -> None:
    match = await _with_proposals(app, owner_engine, worker_engine, books)
    async with signed_in(app, books.reviewer.email) as reviewer:
        pending = await _period(reviewer, books.setup, "close")
        async with signed_in(app, books.analyst.email) as analyst:
            await _decide(analyst, match, "confirm")
        still_pending = await _period(reviewer, books.setup, "close")
        await _decide(reviewer, match, "approve")
        closed = await _period(reviewer, books.setup, "close")
        after_close = await _closed(reviewer, books.setup)
        reverted = await _decide(reviewer, match, "revert", reason="Error")
        no_reason = await _period(reviewer, books.setup, "reopen", reason="  ")
        reopened = await _period(reviewer, books.setup, "reopen", reason="Faltó un abono")
        after_reopen = await _closed(reviewer, books.setup)

    assert (pending.status_code, pending.json()["detail"]) == (409, "pending_matches")
    assert (still_pending.status_code, still_pending.json()["detail"]) == (409, "pending_matches")
    assert closed.status_code == 201
    assert closed.json()["action"] == "close"
    assert after_close[JANUARY] is True
    assert (reverted.status_code, reverted.json()["detail"]) == (409, "closed_period")
    assert (no_reason.status_code, no_reason.json()["detail"]) == (422, "reason_required")
    assert reopened.status_code == 201
    assert reopened.json()["reason"] == "Faltó un abono"
    assert after_reopen[JANUARY] is False
    async with owner_engine.connect() as connection:
        events = (
            await connection.execute(
                text(
                    """SELECT action, entity, actor_user_id FROM audit_events
                       WHERE organization_id = :org AND action LIKE 'period.%' ORDER BY seq"""
                ),
                {"org": books.setup.organization_id},
            )
        ).all()
    assert [tuple(event) for event in events] == [
        ("period.closed", "period_event", books.reviewer.user_id),
        ("period.reopened", "period_event", books.reviewer.user_id),
    ]


async def test_a_closed_month_takes_no_engine_run(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, books: Books
) -> None:
    match = await _with_proposals(app, owner_engine, worker_engine, books)
    async with signed_in(app, books.analyst.email) as analyst:
        await _decide(analyst, match, "discard")
        async with signed_in(app, books.reviewer.email) as reviewer:
            closed = await _period(reviewer, books.setup, "close")
        refused = await _run_engine(analyst, books.setup)

    assert closed.status_code == 201
    assert (refused.status_code, refused.json()["detail"]) == (409, "closed_period")


async def test_only_reviewers_close_and_reopen(app: FastAPI, books: Books) -> None:
    async with signed_in(app, books.analyst.email) as analyst:
        refused = await _period(analyst, books.setup, "close")

    assert (refused.status_code, refused.json()["detail"]) == (403, "role_required")


@pytest.mark.parametrize(
    ("first", "second", "period", "status", "detail"),
    [
        ("close", "close", JANUARY, 409, "already_closed"),
        (None, "reopen", JANUARY, 409, "not_closed"),
        (None, "close", "2027-03-01", 422, "future_period"),
        (None, "close", "2027-01-15", 422, "invalid_period"),
    ],
)
async def test_closing_and_reopening_alternate_on_past_months(
    app: FastAPI,
    books: Books,
    first: str | None,
    second: str,
    period: str,
    status: int,
    detail: str,
) -> None:
    async with signed_in(app, books.reviewer.email) as reviewer:
        if first:
            await _period(reviewer, books.setup, first)
        response = await _period(reviewer, books.setup, second, period, reason="Motivo")

    assert (response.status_code, response.json()["detail"]) == (status, detail)


async def test_closing_is_idempotent_on_the_client_id(app: FastAPI, books: Books) -> None:
    event_id = client_id()
    async with signed_in(app, books.reviewer.email) as reviewer:
        closed = await _period(reviewer, books.setup, "close", id=event_id)
        replay = await _period(reviewer, books.setup, "close", id=event_id)
        reused = await _period(reviewer, books.setup, "close", "2027-02-01", id=event_id)
        not_v7 = await _period(reviewer, books.setup, "close", "2027-02-01", id=str(uuid4()))
    async with signed_in(app, books.other_reviewer.email) as other:
        someone_else = await _period(other, books.setup, "close", id=event_id)

    assert (closed.status_code, replay.status_code) == (201, 200)
    assert replay.json() == closed.json()
    assert (reused.status_code, reused.json()["detail"]) == (409, "id_conflict")
    assert (not_v7.status_code, not_v7.json()["detail"]) == (422, "id_not_uuid7")
    assert (someone_else.status_code, someone_else.json()["detail"]) == (409, "id_conflict")


async def test_periods_stay_inside_their_organization(
    app: FastAPI, owner_engine: AsyncEngine, books: Books
) -> None:
    stranger = await statement_setup(owner_engine, ["reviewer"])
    async with signed_in(app, books.reviewer.email) as reviewer:
        closed = await _period(reviewer, books.setup, "close")
    async with signed_in(app, stranger.member.email) as client:
        foreign = await _period(client, books.setup, "close", "2027-02-01")
        taken_id = await _period(client, stranger, "close", id=closed.json()["id"])

    assert closed.status_code == 201
    assert (foreign.status_code, foreign.json()["detail"]) == (404, "not_found")
    assert (taken_id.status_code, taken_id.json()["detail"]) == (409, "id_conflict")


async def test_two_reviewers_closing_at_once_record_one_close(app: FastAPI, books: Books) -> None:
    async with (
        signed_in(app, books.reviewer.email) as first,
        signed_in(app, books.other_reviewer.email) as second,
    ):
        responses = await asyncio.gather(
            _period(first, books.setup, "close"), _period(second, books.setup, "close")
        )

    assert sorted(response.status_code for response in responses) == [201, 409]
    assert {response.json().get("detail") for response in responses} == {None, "already_closed"}
