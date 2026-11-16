from collections.abc import AsyncIterator
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
    CHANGED_RECEIVABLES,
    NOW,
    RECEIVABLES,
    AlwaysActive,
    Setup,
    receivables_profile,
    receivables_setup,
    statement_setup,
    stored_receivables,
    upload,
    work,
)

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
    profile_id: UUID,
    worker_engine: AsyncEngine,
    clock: FixedClock,
    content: bytes = RECEIVABLES,
) -> str:
    response = await upload(client, setup, content, profile_id=profile_id)
    await work(worker_engine, clock)
    file_id: str = response.json()["file"]["id"]
    return file_id


async def _confirmed(
    client: httpx.AsyncClient,
    setup: Setup,
    profile_id: UUID,
    worker_engine: AsyncEngine,
    clock: FixedClock,
    content: bytes = RECEIVABLES,
) -> str:
    file_id = await _previewed(client, setup, profile_id, worker_engine, clock, content)
    await client.post(f"/api/app/imports/{file_id}/confirm", headers=xsrf_header(client))
    await work(worker_engine, clock)
    return file_id


async def _rows(client: httpx.AsyncClient, file_id: str, status: str) -> list[dict[str, Any]]:
    response = await client.get(f"/api/app/imports/{file_id}/rows", params={"status": status})
    rows: list[dict[str, Any]] = response.json()["rows"]
    return rows


async def test_a_receivables_preview_shows_new_rows_and_errors(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    setup, profile_id = await receivables_setup(owner_engine)
    async with signed_in(app, setup.member.email) as client:
        response = await upload(client, setup, RECEIVABLES, profile_id=profile_id)
        await work(worker_engine, clock)
        file_id = response.json()["file"]["id"]
        summary = (await client.get(f"/api/app/imports/{file_id}")).json()
        ok = await _rows(client, file_id, "ok")
        errors = await _rows(client, file_id, "error")

    assert response.json()["file"]["kind"] == "receivables"
    assert response.json()["file"]["bank_account_id"] is None
    assert summary["file"]["status"] == "previewed"
    assert (summary["counts"]["ok"], summary["counts"]["error"]) == (2, 1)
    assert ok[0] == {
        "kind": "receivable",
        "row_number": 2,
        "status": "ok",
        "action": "create",
        "conflict": None,
        "customer_name": "Comercial Andina SAC",
        "customer_tax_id": "20512345678",
        "doc_number": "F001-00000123",
        "issued_on": "2027-01-02",
        "due_on": "2027-01-31",
        "amount_cents": 118_000,
        "previous_due_on": None,
        "previous_amount_cents": None,
    }
    assert [(row["row_number"], row["error_code"]) for row in errors] == [(4, "missing_amount")]


async def test_confirming_creates_the_receivables(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    setup, profile_id = await receivables_setup(owner_engine)
    async with signed_in(app, setup.member.email) as client:
        await _confirmed(client, setup, profile_id, worker_engine, clock)

    assert await stored_receivables(owner_engine, setup) == [
        ("F001-123", 118_000, None),
        ("F001-124", 50_000, None),
    ]
    async with owner_engine.connect() as connection:
        names = list(
            await connection.scalars(
                text(
                    """SELECT customer_name_norm FROM receivables
                       WHERE organization_id = :org ORDER BY due_on"""
                ),
                {"org": setup.organization_id},
            )
        )
        actions = list(
            await connection.scalars(
                text("SELECT action FROM audit_events WHERE organization_id = :org ORDER BY seq"),
                {"org": setup.organization_id},
            )
        )
    assert names == ["COMERCIAL ANDINA SAC", "GLORIA SA"]
    assert actions == ["import.uploaded", "import.confirmed"]


async def test_reimporting_updates_changed_receivables_and_skips_unchanged_ones(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    setup, profile_id = await receivables_setup(owner_engine)
    async with signed_in(app, setup.member.email) as client:
        await _confirmed(client, setup, profile_id, worker_engine, clock)
        file_id = await _previewed(
            client, setup, profile_id, worker_engine, clock, CHANGED_RECEIVABLES
        )
        ok = await _rows(client, file_id, "ok")
        unchanged = await _rows(client, file_id, "duplicate")
        await client.post(f"/api/app/imports/{file_id}/confirm", headers=xsrf_header(client))
        await work(worker_engine, clock)

    assert [(row["doc_number"], row["action"]) for row in ok] == [
        ("F1-123", "update"),
        ("F001-126", "create"),
    ]
    assert (ok[0]["previous_due_on"], ok[0]["previous_amount_cents"]) == ("2027-01-31", 118_000)
    assert [(row["doc_number"], row["action"]) for row in unchanged] == [("F001-124", "unchanged")]
    assert await stored_receivables(owner_engine, setup) == [
        ("F001-124", 50_000, None),
        ("F001-126", 7_550, None),
        ("F001-123", 120_000, None),
    ]


async def test_voiding_a_receivables_import_cancels_what_it_created(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    setup, profile_id = await receivables_setup(owner_engine)
    async with signed_in(app, setup.member.email) as client:
        file_id = await _confirmed(client, setup, profile_id, worker_engine, clock)
        voided = [
            await client.post(
                f"/api/app/imports/{file_id}/void",
                json={"reason": "Archivo equivocado"},
                headers=xsrf_header(client),
            )
            for _ in range(2)
        ]
        summary = (await client.get(f"/api/app/imports/{file_id}")).json()
        again = await _previewed(client, setup, profile_id, worker_engine, clock)
        conflicts = await _rows(client, again, "conflict")

    assert [response.status_code for response in voided] == [204, 204]
    assert summary["file"]["status"] == "voided"
    assert await stored_receivables(owner_engine, setup) == [
        ("F001-123", 118_000, "Archivo equivocado"),
        ("F001-124", 50_000, "Archivo equivocado"),
    ]
    assert [(row["doc_number"], row["conflict"]) for row in conflicts] == [
        ("F001-00000123", "cancelled"),
        ("F001-124", "cancelled"),
    ]


async def test_the_same_receivables_file_cannot_be_confirmed_twice(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    setup, profile_id = await receivables_setup(owner_engine)
    async with signed_in(app, setup.member.email) as client:
        first = await _confirmed(client, setup, profile_id, worker_engine, clock)
        repeated = await upload(client, setup, RECEIVABLES, profile_id=profile_id)
        await work(worker_engine, clock)
        refused = await client.post(
            f"/api/app/imports/{repeated.json()['file']['id']}/confirm",
            headers=xsrf_header(client),
        )

    assert repeated.json()["duplicate_of"] == first
    assert (refused.status_code, refused.json()["detail"]) == (409, "duplicate_file")


async def test_an_import_with_receivables_in_pending_matches_cannot_be_voided(
    app: FastAPI,
    owner_engine: AsyncEngine,
    worker_engine: AsyncEngine,
    app_engine: AsyncEngine,
    clock: FixedClock,
) -> None:
    setup, profile_id = await receivables_setup(owner_engine)
    async with signed_in(app, setup.member.email) as client:
        file_id = await _confirmed(client, setup, profile_id, worker_engine, clock)
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


async def test_rerunning_confirm_import_does_not_duplicate_receivables(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    setup, profile_id = await receivables_setup(owner_engine)
    async with signed_in(app, setup.member.email) as client:
        file_id = await _confirmed(client, setup, profile_id, worker_engine, clock)
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

    assert len(await stored_receivables(owner_engine, setup)) == 2


async def test_document_numbers_are_matched_only_inside_the_organization(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    setup, profile_id = await receivables_setup(owner_engine)
    other = await statement_setup(owner_engine)
    other_profile = await receivables_profile(owner_engine, other)
    async with signed_in(app, setup.member.email) as client:
        first = await _confirmed(client, setup, profile_id, worker_engine, clock)
    async with signed_in(app, other.member.email) as client:
        response = await upload(client, other, RECEIVABLES, profile_id=other_profile)
        await work(worker_engine, clock)
        second = response.json()["file"]["id"]
        ok = await _rows(client, second, "ok")
        hidden = await client.get(f"/api/app/imports/{first}")

    assert response.json()["duplicate_of"] is None
    assert [row["action"] for row in ok] == ["create", "create"]
    assert hidden.status_code == 404
