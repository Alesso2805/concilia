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
from concilia.shared.kernel.principal import Principal
from tests.support.api import add_member, build_app, signed_in, xsrf_header
from tests.support.clock import FixedClock
from tests.support.database import DatabaseUrls
from tests.support.imports import (
    CHANGED_RECEIVABLES,
    NOW,
    RECEIVABLES,
    AlwaysActive,
    Setup,
    receivables_setup,
    statement_setup,
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


async def _import(
    client: httpx.AsyncClient,
    setup: Setup,
    profile_id: UUID,
    worker_engine: AsyncEngine,
    clock: FixedClock,
    content: bytes = RECEIVABLES,
    confirm: bool = True,
) -> str:
    response = await upload(client, setup, content, profile_id=profile_id)
    await work(worker_engine, clock)
    file_id: str = response.json()["file"]["id"]
    if confirm:
        await client.post(f"/api/app/imports/{file_id}/confirm", headers=xsrf_header(client))
        await work(worker_engine, clock)
    return file_id


async def _page(client: httpx.AsyncClient, **params: Any) -> dict[str, Any]:
    response = await client.get("/api/app/receivables", params=params)
    page: dict[str, Any] = response.json()
    return page


def _documents(page: dict[str, Any]) -> list[str]:
    return [item["doc_number"] for item in page["receivables"]]


async def _cancel(client: httpx.AsyncClient, receivable_id: str) -> httpx.Response:
    return await client.post(
        f"/api/app/receivables/{receivable_id}/cancel",
        json={"reason": "Nota de crédito"},
        headers=xsrf_header(client),
    )


async def test_receivables_are_listed_by_due_date_with_keyset_pages(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    setup, profile_id = await receivables_setup(owner_engine)
    async with signed_in(app, setup.member.email) as client:
        await _import(client, setup, profile_id, worker_engine, clock)
        await _import(client, setup, profile_id, worker_engine, clock, CHANGED_RECEIVABLES)
        everything = await _page(client)
        first = await _page(client, limit=2)
        second = await _page(client, limit=2, after=first["next_cursor"])
        back = await _page(client, limit=2, before=second["previous_cursor"])
        invalid = await client.get("/api/app/receivables", params={"after": "nope"})

    assert _documents(everything) == ["F001-124", "F001-126", "F001-00000123"]
    assert everything["receivables"][2]["amount_cents"] == 120_000
    assert (_documents(first), first["has_previous"], first["has_next"]) == (
        ["F001-124", "F001-126"],
        False,
        True,
    )
    assert (_documents(second), second["has_previous"], second["has_next"]) == (
        ["F001-00000123"],
        True,
        False,
    )
    assert (_documents(back), back["has_previous"], back["has_next"]) == (
        ["F001-124", "F001-126"],
        False,
        True,
    )
    assert (invalid.status_code, invalid.json()["detail"]) == (422, "invalid_cursor")


async def test_a_document_is_found_in_any_accepted_spelling(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    setup, profile_id = await receivables_setup(owner_engine)
    async with signed_in(app, setup.member.email) as client:
        await _import(client, setup, profile_id, worker_engine, clock)
        found = await _page(client, document="f1-123")
        cancelled = await _page(client, document="F001-123", cancelled=True)
        invalid = await client.get("/api/app/receivables", params={"document": "FACTURA"})

    assert _documents(found) == ["F001-00000123"]
    assert _documents(cancelled) == []
    assert (invalid.status_code, invalid.json()["detail"]) == (422, "invalid_document")


async def test_cancelling_moves_a_receivable_to_the_cancelled_list(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    setup, profile_id = await receivables_setup(owner_engine)
    async with signed_in(app, setup.member.email) as client:
        await _import(client, setup, profile_id, worker_engine, clock)
        [first, _] = (await _page(client))["receivables"]
        cancelled = [await _cancel(client, first["id"]) for _ in range(2)]
        live = await _page(client)
        gone = await _page(client, cancelled=True)
        preview = await _import(
            client, setup, profile_id, worker_engine, clock, CHANGED_RECEIVABLES, confirm=False
        )
        conflicts = (
            await client.get(f"/api/app/imports/{preview}/rows", params={"status": "conflict"})
        ).json()["rows"]
        missing = await _cancel(client, str(uuid7()))

    assert [response.status_code for response in cancelled] == [204, 204]
    assert _documents(live) == ["F001-124"]
    assert [(item["doc_number"], item["cancel_reason"]) for item in gone["receivables"]] == [
        ("F001-00000123", "Nota de crédito")
    ]
    assert gone["receivables"][0]["cancelled_at"] is not None
    assert [(row["doc_number"], row["conflict"]) for row in conflicts] == [("F1-123", "cancelled")]
    assert (missing.status_code, missing.json()["detail"]) == (404, "not_found")
    async with owner_engine.connect() as connection:
        events = (
            await connection.execute(
                text(
                    """SELECT entity, entity_id, metadata FROM audit_events
                       WHERE organization_id = :org AND action = 'receivable.cancelled'"""
                ),
                {"org": setup.organization_id},
            )
        ).all()
    assert [(event.entity, str(event.entity_id), event.metadata) for event in events] == [
        ("receivable", first["id"], {})
    ]


async def test_a_receivable_in_a_pending_match_cannot_be_cancelled(
    app: FastAPI,
    owner_engine: AsyncEngine,
    worker_engine: AsyncEngine,
    app_engine: AsyncEngine,
    clock: FixedClock,
) -> None:
    setup, profile_id = await receivables_setup(owner_engine)
    async with signed_in(app, setup.member.email) as client:
        await _import(client, setup, profile_id, worker_engine, clock)
        [first, _] = (await _page(client))["receivables"]
    service = ImportService(
        SqlImportTransactions(app_engine, SqlAuditRecorder, SqlPeriodQueries, AlwaysActive),
        ContentReader(),
        clock,
    )
    analyst = Principal(
        setup.member.user_id, uuid7(), setup.organization_id, frozenset({"analyst"})
    )

    with pytest.raises(ActiveMatchesError):
        await service.cancel_receivable(analyst, UUID(first["id"]), "Nota de crédito")


async def test_receivables_stay_inside_their_organization(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    setup, profile_id = await receivables_setup(owner_engine)
    other = await statement_setup(owner_engine)
    async with signed_in(app, setup.member.email) as client:
        await _import(client, setup, profile_id, worker_engine, clock)
        [first, _] = (await _page(client))["receivables"]
    async with signed_in(app, other.member.email) as client:
        listed = await _page(client)
        refused = await _cancel(client, first["id"])

    assert listed["receivables"] == []
    assert (refused.status_code, refused.json()["detail"]) == (404, "not_found")


async def test_every_member_lists_receivables_but_only_analysts_cancel(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    setup, profile_id = await receivables_setup(owner_engine)
    reviewer = await add_member(owner_engine, NOW, setup.organization_id, ["reviewer"])
    async with signed_in(app, setup.member.email) as client:
        await _import(client, setup, profile_id, worker_engine, clock)
        [first, _] = (await _page(client))["receivables"]
    async with signed_in(app, reviewer.email) as client:
        listed = await _page(client)
        refused = await _cancel(client, first["id"])

    assert len(listed["receivables"]) == 2
    assert (refused.status_code, refused.json()["detail"]) == (403, "role_required")
