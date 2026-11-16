import asyncio
from collections.abc import AsyncIterator
from datetime import date
from typing import Any
from uuid import UUID, uuid7

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from concilia.shared.infrastructure.jobs import Runner, enqueue
from concilia.worker import handlers
from tests.support.api import add_member, build_app, signed_in, xsrf_header
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

JANUARY, FEBRUARY = date(2027, 1, 1), date(2027, 2, 1)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
async def app(database: DatabaseUrls, clock: FixedClock) -> AsyncIterator[FastAPI]:
    app = build_app(database.for_role("concilia_app"), clock)
    yield app
    await app.state.engine.dispose()


async def _import(
    client: httpx.AsyncClient,
    setup: Setup,
    worker_engine: AsyncEngine,
    clock: FixedClock,
    content: bytes,
    profile_id: UUID | None = None,
) -> None:
    response = await upload(client, setup, content, profile_id=profile_id)
    await work(worker_engine, clock)
    file_id = response.json()["file"]["id"]
    await client.post(f"/api/app/imports/{file_id}/confirm", headers=xsrf_header(client))
    await work(worker_engine, clock)


@pytest.fixture
async def setup(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> Setup:
    setup = await statement_setup(owner_engine)
    profile_id = await receivables_profile(owner_engine, setup)
    async with signed_in(app, setup.member.email) as client:
        await _import(client, setup, worker_engine, clock, STATEMENT)
        await _import(client, setup, worker_engine, clock, RECEIVABLES, profile_id)
    return setup


async def _request(
    client: httpx.AsyncClient, setup: Setup, period: date, run_id: str | None = None
) -> httpx.Response:
    return await client.post(
        "/api/app/engine-runs",
        json={
            "id": run_id or client_id(),
            "bank_account_id": str(setup.account_id),
            "period": period.isoformat(),
        },
        headers=xsrf_header(client),
    )


async def _proposals(owner_engine: AsyncEngine, setup: Setup) -> list[tuple[Any, ...]]:
    async with owner_engine.connect() as connection:
        rows = await connection.execute(
            text(
                """SELECT m.rule, m.score, m.explanation, b.amount_cents, r.doc_number_norm,
                          i.applied_cents
                   FROM matches m
                   JOIN match_items c ON c.match_id = m.id AND c.bank_movement_id IS NOT NULL
                   JOIN bank_movements b ON b.id = c.bank_movement_id
                   JOIN match_items i ON i.match_id = m.id AND i.receivable_id IS NOT NULL
                   JOIN receivables r ON r.id = i.receivable_id
                   WHERE m.organization_id = :org ORDER BY b.booked_on"""
            ),
            {"org": setup.organization_id},
        )
        return [tuple(row) for row in rows]


async def test_a_run_proposes_matches_for_the_free_credits_of_the_month(
    app: FastAPI,
    owner_engine: AsyncEngine,
    worker_engine: AsyncEngine,
    clock: FixedClock,
    setup: Setup,
) -> None:
    async with signed_in(app, setup.member.email) as client:
        requested = await _request(client, setup, JANUARY)
        assert await work(worker_engine, clock) == 1
        run = (await client.get(f"/api/app/engine-runs/{requested.json()['id']}")).json()
        job = (await client.get(f"/api/app/jobs/{run['job_id']}")).json()

    assert requested.status_code == 201
    assert (run["proposals_count"], run["finished_at"] is not None) == (1, True)
    assert (job["status"], job["progress"]) == ("done", 100)
    [proposal] = await _proposals(owner_engine, setup)
    assert proposal[:2] == ("R1", 100)
    assert proposal[2].startswith("La descripción menciona F001-123 y el monto coincide")
    assert proposal[3:] == (118_000, "F001-123", 118_000)
    async with owner_engine.connect() as connection:
        actions = list(
            await connection.scalars(
                text(
                    """SELECT action FROM audit_events
                       WHERE organization_id = :org AND entity = 'engine_run'"""
                ),
                {"org": setup.organization_id},
            )
        )
    assert actions == ["engine_run.requested"]


async def test_running_again_does_not_duplicate_proposals(
    app: FastAPI,
    owner_engine: AsyncEngine,
    worker_engine: AsyncEngine,
    clock: FixedClock,
    setup: Setup,
) -> None:
    async with signed_in(app, setup.member.email) as client:
        first = await _request(client, setup, FEBRUARY)
        await work(worker_engine, clock)
        second = await _request(client, setup, FEBRUARY)
        await work(worker_engine, clock)
        again = (await client.get(f"/api/app/engine-runs/{second.json()['id']}")).json()

    assert first.status_code == second.status_code == 201
    assert again["proposals_count"] == 0
    assert [row[:2] for row in await _proposals(owner_engine, setup)] == [("R6", 60)]


async def test_rerunning_the_same_job_does_not_duplicate_proposals(
    app: FastAPI,
    owner_engine: AsyncEngine,
    worker_engine: AsyncEngine,
    clock: FixedClock,
    setup: Setup,
) -> None:
    async with signed_in(app, setup.member.email) as client:
        run_id = (await _request(client, setup, JANUARY)).json()["id"]
        await work(worker_engine, clock)
    async with worker_engine.begin() as connection:
        await enqueue(
            connection,
            job_id=uuid7(),
            kind="run_engine",
            now=NOW,
            organization_id=setup.organization_id,
            payload={"engine_run_id": run_id},
        )
    assert await work(worker_engine, clock) == 1

    assert len(await _proposals(owner_engine, setup)) == 1


async def test_a_refused_combination_is_not_proposed_again_in_the_month(
    app: FastAPI,
    owner_engine: AsyncEngine,
    worker_engine: AsyncEngine,
    clock: FixedClock,
    setup: Setup,
) -> None:
    async with signed_in(app, setup.member.email) as client:
        await _request(client, setup, FEBRUARY)
        await work(worker_engine, clock)
        async with owner_engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO match_decisions (id, organization_id, match_id, action,
                                                    decided_by, decided_at)
                       SELECT gen_random_uuid(), organization_id, id, 'discard', :user, :now
                       FROM matches WHERE organization_id = :org"""
                ),
                {"org": setup.organization_id, "user": setup.member.user_id, "now": NOW},
            )
        second = await _request(client, setup, FEBRUARY)
        await work(worker_engine, clock)
        run = (await client.get(f"/api/app/engine-runs/{second.json()['id']}")).json()

    assert run["proposals_count"] == 0


async def test_closed_months_and_runs_in_progress_are_refused(
    app: FastAPI,
    owner_engine: AsyncEngine,
    worker_engine: AsyncEngine,
    clock: FixedClock,
    setup: Setup,
) -> None:
    async with signed_in(app, setup.member.email) as client:
        queued = await _request(client, setup, JANUARY)
        busy = await _request(client, setup, JANUARY)
        async with owner_engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO period_events (id, organization_id, bank_account_id, period,
                                                  action, decided_by, decided_at)
                       VALUES (gen_random_uuid(), :org, :account, :period, 'close', :user, :now)"""
                ),
                {
                    "org": setup.organization_id,
                    "account": setup.account_id,
                    "period": JANUARY,
                    "user": setup.member.user_id,
                    "now": NOW,
                },
            )
        closed = await _request(client, setup, JANUARY)
        await work(worker_engine, clock)
        job = (await client.get(f"/api/app/jobs/{queued.json()['job_id']}")).json()

    assert (busy.status_code, busy.json()["detail"]) == (409, "run_in_progress")
    assert (closed.status_code, closed.json()["detail"]) == (409, "closed_period")
    assert (job["status"], job["error_code"]) == ("failed", "closed_period")
    assert await _proposals(owner_engine, setup) == []


async def test_requests_are_idempotent_and_validated(
    app: FastAPI, worker_engine: AsyncEngine, clock: FixedClock, setup: Setup
) -> None:
    run_id = client_id()
    async with signed_in(app, setup.member.email) as client:
        first = await _request(client, setup, JANUARY, run_id)
        replay = await _request(client, setup, JANUARY, run_id)
        conflict = await _request(client, setup, FEBRUARY, run_id)
        mid_month = await _request(client, setup, date(2027, 1, 15))
        unknown = await client.post(
            "/api/app/engine-runs",
            json={"id": client_id(), "bank_account_id": str(uuid7()), "period": "2027-01-01"},
            headers=xsrf_header(client),
        )

    assert (first.status_code, replay.status_code) == (201, 200)
    assert replay.json() == first.json()
    assert (conflict.status_code, conflict.json()["detail"]) == (409, "id_conflict")
    assert (mid_month.status_code, mid_month.json()["detail"]) == (422, "invalid_period")
    assert (unknown.status_code, unknown.json()["detail"]) == (404, "not_found")


async def test_runs_stay_inside_their_organization_and_need_an_analyst(
    app: FastAPI, owner_engine: AsyncEngine, setup: Setup
) -> None:
    other = await statement_setup(owner_engine)
    reviewer = await add_member(owner_engine, NOW, setup.organization_id, ["reviewer"])
    async with signed_in(app, setup.member.email) as client:
        run_id = (await _request(client, setup, JANUARY)).json()["id"]
    async with signed_in(app, other.member.email) as client:
        hidden = await client.get(f"/api/app/engine-runs/{run_id}")
        foreign = await _request(client, setup, FEBRUARY)
    async with signed_in(app, reviewer.email) as client:
        visible = await client.get(f"/api/app/engine-runs/{run_id}")
        refused = await _request(client, setup, FEBRUARY)

    assert (hidden.status_code, foreign.status_code) == (404, 404)
    assert visible.status_code == 200
    assert (refused.status_code, refused.json()["detail"]) == (403, "role_required")


async def test_runs_on_two_accounts_at_once_share_a_receivable_without_overdrawing_it(
    app: FastAPI,
    owner_engine: AsyncEngine,
    worker_engine: AsyncEngine,
    clock: FixedClock,
    setup: Setup,
) -> None:
    second_account = uuid7()
    async with owner_engine.begin() as connection:
        await connection.execute(
            text(
                """INSERT INTO bank_accounts (id, organization_id, bank, currency, alias,
                                              number_last4, created_at)
                   VALUES (:id, :org, 'BBVA', 'PEN', 'Secundaria', '9876', :now)"""
            ),
            {"id": second_account, "org": setup.organization_id, "now": NOW},
        )
        await connection.execute(
            text(
                """INSERT INTO bank_movements (id, organization_id, bank_account_id,
                                               import_file_id, booked_on, amount_cents,
                                               description, description_norm, fingerprint,
                                               doc_refs, created_at)
                   SELECT gen_random_uuid(), organization_id, :account, import_file_id,
                          booked_on, amount_cents, description, description_norm,
                          :fingerprint, doc_refs, :now
                   FROM bank_movements
                   WHERE organization_id = :org AND amount_cents = 118000"""
            ),
            {
                "account": second_account,
                "org": setup.organization_id,
                "fingerprint": "f" * 64,
                "now": NOW,
            },
        )
    async with signed_in(app, setup.member.email) as client:
        for account in (setup.account_id, second_account):
            await client.post(
                "/api/app/engine-runs",
                json={"id": client_id(), "bank_account_id": str(account), "period": "2027-01-01"},
                headers=xsrf_header(client),
            )

    runners = [Runner(worker_engine, clock, handlers(worker_engine, clock)) for _ in range(2)]
    claimed = await asyncio.gather(*(runner.run_once() for runner in runners))

    async with owner_engine.connect() as connection:
        proposed = await connection.scalar(
            text(
                """SELECT count(*) FROM match_items i JOIN receivables r ON r.id = i.receivable_id
                   WHERE r.organization_id = :org AND r.doc_number_norm = 'F001-123'"""
            ),
            {"org": setup.organization_id},
        )
        available = await connection.scalar(
            text(
                """SELECT b.available_cents FROM receivable_balances b
                   JOIN receivables r ON r.id = b.receivable_id
                   WHERE r.organization_id = :org AND r.doc_number_norm = 'F001-123'"""
            ),
            {"org": setup.organization_id},
        )
        statuses = list(
            await connection.scalars(
                text(
                    "SELECT status FROM jobs WHERE organization_id = :org AND kind = 'run_engine'"
                ),
                {"org": setup.organization_id},
            )
        )
    assert claimed == [True, True]
    assert statuses == ["done", "done"]
    assert (proposed, available) == (1, 0)
