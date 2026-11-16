from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from concilia.imports.application.matches import ActiveMatchesQuery
from concilia.matching.infrastructure.queries import SqlMatchQueries
from concilia.periods.application.pending import PendingMatchesQuery
from concilia.shared.infrastructure.db import organization_transaction
from tests.support.api import add_member, build_app, signed_in, xsrf_header
from tests.support.clock import FixedClock
from tests.support.database import DatabaseUrls
from tests.support.imports import (
    CHANGED_RECEIVABLES,
    NOW,
    RECEIVABLES,
    STATEMENT,
    Setup,
    receivables_profile,
    statement_setup,
    upload,
    work,
)
from tests.support.matches import insert_match

pytestmark = pytest.mark.anyio


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
    reviewer: UUID
    profile_id: UUID
    statement_id: str
    january: UUID
    february: UUID
    proposed_receivable: UUID
    approved_receivable: UUID
    proposed: UUID


async def _confirmed(
    client: httpx.AsyncClient,
    setup: Setup,
    worker_engine: AsyncEngine,
    clock: FixedClock,
    content: bytes = STATEMENT,
    profile_id: UUID | None = None,
) -> str:
    response = await upload(client, setup, content, profile_id=profile_id)
    await work(worker_engine, clock)
    file_id: str = response.json()["file"]["id"]
    await client.post(f"/api/app/imports/{file_id}/confirm", headers=xsrf_header(client))
    await work(worker_engine, clock)
    return file_id


async def _ids(owner_engine: AsyncEngine, sql: str, organization_id: UUID) -> list[UUID]:
    async with owner_engine.connect() as connection:
        return list(await connection.scalars(text(sql), {"org": organization_id}))


@pytest.fixture
async def books(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> Books:
    setup = await statement_setup(owner_engine)
    reviewer = await add_member(owner_engine, NOW, setup.organization_id, ["reviewer"])
    profile_id = await receivables_profile(owner_engine, setup)
    async with signed_in(app, setup.member.email) as client:
        statement_id = await _confirmed(client, setup, worker_engine, clock)
        await _confirmed(client, setup, worker_engine, clock, RECEIVABLES, profile_id)
    january, february = await _ids(
        owner_engine,
        """SELECT id FROM bank_movements
           WHERE organization_id = :org AND amount_cents > 0 ORDER BY booked_on""",
        setup.organization_id,
    )
    first, second = await _ids(
        owner_engine,
        "SELECT id FROM receivables WHERE organization_id = :org ORDER BY doc_number_norm",
        setup.organization_id,
    )
    proposed = await insert_match(
        owner_engine,
        organization_id=setup.organization_id,
        bank_account_id=setup.account_id,
        created_by=setup.member.user_id,
        credits=[january],
        applications=[(first, 118_000)],
        at=NOW,
    )
    await insert_match(
        owner_engine,
        organization_id=setup.organization_id,
        bank_account_id=setup.account_id,
        created_by=setup.member.user_id,
        credits=[february],
        applications=[(second, 50_000)],
        decisions=[("confirm", setup.member.user_id), ("approve", reviewer.user_id)],
        at=NOW,
    )
    return Books(
        setup,
        reviewer.user_id,
        profile_id,
        statement_id,
        january,
        february,
        first,
        second,
        proposed,
    )


async def test_the_queries_tell_active_and_pending_matches_apart(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, books: Books
) -> None:
    async with organization_transaction(app_engine, books.setup.organization_id) as connection:
        queries = SqlMatchQueries(connection)
        active_query: ActiveMatchesQuery = queries
        pending_query: PendingMatchesQuery = queries
        movements = [books.january, books.february]
        receivables = [books.proposed_receivable, books.approved_receivable]
        active = await active_query.active(movements, receivables)
        pending = await pending_query.any_pending(books.setup.account_id, date(2027, 1, 1))
        approved_month = await pending_query.any_pending(books.setup.account_id, date(2027, 2, 1))
        assert await queries.pending(movements, receivables) == {
            books.january,
            books.proposed_receivable,
        }
        assert await queries.active([], []) == set()

    assert active == {*movements, *receivables}
    assert (pending, approved_month) == (True, False)


async def test_a_discarded_match_frees_its_items(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, books: Books
) -> None:
    async with owner_engine.begin() as connection:
        await connection.execute(
            text(
                """INSERT INTO match_decisions (id, organization_id, match_id, action, decided_by,
                                                decided_at)
                   VALUES (gen_random_uuid(), :org, :match, 'discard', :user, :now)"""
            ),
            {
                "org": books.setup.organization_id,
                "match": books.proposed,
                "user": books.setup.member.user_id,
                "now": NOW,
            },
        )

    async with organization_transaction(app_engine, books.setup.organization_id) as connection:
        queries = SqlMatchQueries(connection)
        active = await queries.active([books.january], [books.proposed_receivable])
        pending = await queries.any_pending(books.setup.account_id, date(2027, 1, 1))

    assert (active, pending) == (set(), False)


async def test_imports_respect_matches_through_the_api(
    app: FastAPI, worker_engine: AsyncEngine, clock: FixedClock, books: Books
) -> None:
    async with signed_in(app, books.setup.member.email) as client:
        voided = await client.post(
            f"/api/app/imports/{books.statement_id}/void",
            json={"reason": "Archivo equivocado"},
            headers=xsrf_header(client),
        )
        pending = await client.post(
            f"/api/app/receivables/{books.proposed_receivable}/cancel",
            json={"reason": "Nota de crédito"},
            headers=xsrf_header(client),
        )
        approved = await client.post(
            f"/api/app/receivables/{books.approved_receivable}/cancel",
            json={"reason": "Nota de crédito"},
            headers=xsrf_header(client),
        )
        response = await upload(
            client, books.setup, CHANGED_RECEIVABLES, profile_id=books.profile_id
        )
        await work(worker_engine, clock)
        file_id = response.json()["file"]["id"]
        conflicts = (
            await client.get(f"/api/app/imports/{file_id}/rows", params={"status": "conflict"})
        ).json()["rows"]

    assert (voided.status_code, voided.json()["detail"]) == (409, "active_matches")
    assert (pending.status_code, pending.json()["detail"]) == (409, "active_matches")
    assert approved.status_code == 204
    assert [(row["doc_number"], row["conflict"]) for row in conflicts] == [
        ("F1-123", "active_matches"),
        ("F001-124", "cancelled"),
    ]
