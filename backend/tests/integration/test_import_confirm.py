from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid7

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from concilia.audit.infrastructure.sql import SqlAuditRecorder
from concilia.imports.application.service import ActiveMatchesError, ImportService
from concilia.imports.infrastructure.jobs import ContentReader
from concilia.imports.infrastructure.sql import SqlImportTransactions
from concilia.periods.infrastructure.sql import SqlPeriodQueries
from concilia.shared.infrastructure.jobs import enqueue
from concilia.shared.kernel.principal import Principal
from tests.support.api import build_app, signed_in, xsrf_header
from tests.support.clock import FixedClock
from tests.support.database import DatabaseUrls
from tests.support.imports import (
    NOW,
    STATEMENT,
    AlwaysActive,
    Setup,
    statement_setup,
    upload,
    work,
)
from tests.support.statistics import all_grew, manual_analyze_counts

pytestmark = pytest.mark.anyio


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
async def app(database: DatabaseUrls, clock: FixedClock) -> AsyncIterator[FastAPI]:
    app = build_app(database.for_role("concilia_app"), clock)
    yield app
    await app.state.engine.dispose()


async def _previewed(
    client: httpx.AsyncClient,
    setup: Setup,
    worker_engine: AsyncEngine,
    clock: FixedClock,
    content: bytes = STATEMENT,
) -> str:
    file_id: str = (await upload(client, setup, content)).json()["file"]["id"]
    await work(worker_engine, clock)
    return file_id


async def _confirm(client: httpx.AsyncClient, file_id: str) -> httpx.Response:
    return await client.post(f"/api/app/imports/{file_id}/confirm", headers=xsrf_header(client))


async def _void(client: httpx.AsyncClient, file_id: str, reason: str = "Archivo equivocado") -> Any:
    return await client.post(
        f"/api/app/imports/{file_id}/void", json={"reason": reason}, headers=xsrf_header(client)
    )


async def _movements(owner_engine: AsyncEngine, setup: Setup) -> list[tuple[int, bool]]:
    async with owner_engine.connect() as connection:
        rows = await connection.execute(
            text(
                """SELECT amount_cents, voided_at IS NOT NULL AS voided FROM bank_movements
                   WHERE bank_account_id = :account ORDER BY booked_on, amount_cents"""
            ),
            {"account": setup.account_id},
        )
        return [(row.amount_cents, row.voided) for row in rows]


async def test_confirming_saves_only_the_valid_rows(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    setup = await statement_setup(owner_engine)
    async with signed_in(app, setup.member.email) as client:
        file_id = await _previewed(client, setup, worker_engine, clock)
        first = await _confirm(client, file_id)
        again = await _confirm(client, file_id)
        assert first.status_code == 202
        assert again.json() == first.json()
        assert await work(worker_engine, clock) == 1
        summary = (await client.get(f"/api/app/imports/{file_id}")).json()

    assert summary["file"]["status"] == "confirmed"
    assert sum(summary["counts"].values()) == 0
    assert await _movements(owner_engine, setup) == [
        (118_000, False),
        (-1_250, False),
        (50_000, False),
    ]
    async with owner_engine.connect() as connection:
        refs = await connection.scalar(
            text(
                """SELECT doc_refs FROM bank_movements
                   WHERE amount_cents = 118000 AND bank_account_id = :a"""
            ),
            {"a": setup.account_id},
        )
        actions = list(
            await connection.scalars(
                text("SELECT action FROM audit_events WHERE organization_id = :org ORDER BY seq"),
                {"org": setup.organization_id},
            )
        )
    assert refs == ["F001-123"]
    assert actions == ["import.uploaded", "import.confirmed"]


async def test_confirming_refreshes_the_planner_statistics(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    setup = await statement_setup(owner_engine)
    async with signed_in(app, setup.member.email) as client:
        file_id = await _previewed(client, setup, worker_engine, clock)
        before = await manual_analyze_counts(owner_engine)
        await _confirm(client, file_id)
        await work(worker_engine, clock)

    assert all_grew(before, await manual_analyze_counts(owner_engine))


async def test_the_same_file_cannot_be_confirmed_twice_in_an_account(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    setup = await statement_setup(owner_engine)
    async with signed_in(app, setup.member.email) as client:
        first = await _previewed(client, setup, worker_engine, clock)
        await _confirm(client, first)
        await work(worker_engine, clock)
        repeated = await upload(client, setup)
        second = repeated.json()["file"]["id"]
        await work(worker_engine, clock)
        counts = (await client.get(f"/api/app/imports/{second}")).json()["counts"]
        refused = await _confirm(client, second)

    assert repeated.json()["duplicate_of"] == first
    assert counts["duplicate"] == 3
    assert (refused.status_code, refused.json()["detail"]) == (409, "duplicate_file")


async def test_rows_that_became_duplicates_after_the_preview_are_skipped(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    setup = await statement_setup(owner_engine)
    overlapping = STATEMENT.replace(b"500,00", b"500,01")
    async with signed_in(app, setup.member.email) as client:
        first = await _previewed(client, setup, worker_engine, clock)
        second = await _previewed(client, setup, worker_engine, clock, overlapping)
        await _confirm(client, first)
        await work(worker_engine, clock)
        await _confirm(client, second)
        await work(worker_engine, clock)

    assert sorted(amount for amount, _ in await _movements(owner_engine, setup)) == [
        -1_250,
        50_000,
        50_001,
        118_000,
    ]


async def test_rerunning_confirm_import_does_not_duplicate_movements(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    setup = await statement_setup(owner_engine)
    async with signed_in(app, setup.member.email) as client:
        file_id = await _previewed(client, setup, worker_engine, clock)
        await _confirm(client, file_id)
    await work(worker_engine, clock)
    async with worker_engine.begin() as connection:
        await enqueue(
            connection,
            job_id=uuid7(),
            kind="confirm_import",
            now=NOW,
            organization_id=setup.organization_id,
            payload={"import_file_id": file_id},
        )
    assert await work(worker_engine, clock) == 1

    assert len(await _movements(owner_engine, setup)) == 3


async def test_voiding_frees_the_movements_for_a_new_import(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    setup = await statement_setup(owner_engine)
    async with signed_in(app, setup.member.email) as client:
        file_id = await _previewed(client, setup, worker_engine, clock)
        early = await _void(client, file_id)
        await _confirm(client, file_id)
        await work(worker_engine, clock)
        voided = [await _void(client, file_id) for _ in range(2)]
        again = await _previewed(client, setup, worker_engine, clock)
        counts = (await client.get(f"/api/app/imports/{again}")).json()["counts"]
        confirmed_again = await _confirm(client, again)

    assert (early.status_code, early.json()["detail"]) == (409, "wrong_state")
    assert [response.status_code for response in voided] == [204, 204]
    assert counts["ok"] == 3
    assert confirmed_again.status_code == 202
    assert [voided for _, voided in await _movements(owner_engine, setup)] == [True] * 3


async def test_movements_in_a_closed_period_cannot_be_voided(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    setup = await statement_setup(owner_engine)
    async with signed_in(app, setup.member.email) as client:
        file_id = await _previewed(client, setup, worker_engine, clock)
        await _confirm(client, file_id)
        await work(worker_engine, clock)
        async with owner_engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO period_events (id, organization_id, bank_account_id, period,
                                                  action, decided_by, decided_at)
                       VALUES (:id, :org, :account, '2027-02-01', 'close', :user, :now)"""
                ),
                {
                    "id": uuid7(),
                    "org": setup.organization_id,
                    "account": setup.account_id,
                    "user": setup.member.user_id,
                    "now": NOW,
                },
            )
        response = await _void(client, file_id)

    assert (response.status_code, response.json()["detail"]) == (409, "closed_period")


async def test_movements_in_active_matches_cannot_be_voided(
    app: FastAPI,
    owner_engine: AsyncEngine,
    worker_engine: AsyncEngine,
    app_engine: AsyncEngine,
    clock: FixedClock,
) -> None:
    setup = await statement_setup(owner_engine)
    async with signed_in(app, setup.member.email) as client:
        file_id = await _previewed(client, setup, worker_engine, clock)
        await _confirm(client, file_id)
        await work(worker_engine, clock)
    service = ImportService(
        SqlImportTransactions(app_engine, SqlAuditRecorder, SqlPeriodQueries, AlwaysActive),
        ContentReader(),
        clock,
    )
    analyst = Principal(
        setup.member.user_id, uuid7(), setup.organization_id, frozenset({"analyst"})
    )

    with pytest.raises(ActiveMatchesError):
        await service.void(analyst, UUID(file_id), "Archivo equivocado")


async def test_cleanup_discards_old_previews_and_abandons_stuck_uploads(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    setup = await statement_setup(owner_engine)
    async with signed_in(app, setup.member.email) as client:
        previewed = await _previewed(client, setup, worker_engine, clock)
        stuck = (await upload(client, setup, STATEMENT + b"09/02/2027;X;1,00\n")).json()["file"][
            "id"
        ]
    async with worker_engine.begin() as connection:
        await connection.execute(
            text("SELECT app_cleanup(:now)"), {"now": NOW + timedelta(hours=23)}
        )
        await connection.execute(
            text("SELECT app_cleanup(:now)"), {"now": NOW + timedelta(hours=25)}
        )
    async with owner_engine.connect() as connection:
        states: dict[str, str] = dict(
            (
                await connection.execute(
                    text("SELECT id::text, status FROM import_files WHERE id::text IN (:a, :b)"),
                    {"a": previewed, "b": stuck},
                )
            ).all()
        )
        rows = await connection.scalar(
            text("SELECT count(*) FROM import_rows WHERE import_file_id::text = :a"),
            {"a": previewed},
        )
    assert states == {previewed: "discarded", stuck: "failed"}
    assert rows == 0


async def test_confirming_and_voiding_stay_within_the_organization(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    setup = await statement_setup(owner_engine)
    other = await statement_setup(owner_engine)
    async with signed_in(app, setup.member.email) as client:
        file_id = await _previewed(client, setup, worker_engine, clock)
    async with signed_in(app, other.member.email) as client:
        responses = [await _confirm(client, file_id), await _void(client, file_id)]

    assert [response.status_code for response in responses] == [404, 404]
