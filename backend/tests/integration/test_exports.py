from collections.abc import AsyncIterator
from datetime import timedelta
from io import BytesIO
from typing import Any
from uuid import uuid7

import httpx
import pytest
from fastapi import FastAPI
from openpyxl import load_workbook
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from concilia.shared.infrastructure.jobs import Runner
from concilia.worker import handlers
from tests.support.api import Member, add_member, build_app, signed_in, xsrf_header
from tests.support.clock import FixedClock
from tests.support.database import DatabaseUrls
from tests.support.imports import NOW, Setup, client_id, statement_setup, work
from tests.support.reporting import reconciled_books

pytestmark = pytest.mark.anyio

ATTACK = '=HYPERLINK("http://example.invalid","clic")'


@pytest.fixture
async def app(database: DatabaseUrls) -> AsyncIterator[FastAPI]:
    app = build_app(database.for_role("concilia_app"), FixedClock(NOW))
    yield app
    await app.state.engine.dispose()


@pytest.fixture
async def books(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine
) -> tuple[Setup, Member]:
    setup, reviewer = await reconciled_books(app, owner_engine, worker_engine)
    async with owner_engine.begin() as connection:
        await connection.execute(
            text(
                """INSERT INTO bank_movements (id, organization_id, bank_account_id,
                                               import_file_id, booked_on, amount_cents,
                                               description, description_norm, fingerprint,
                                               doc_refs, created_at)
                   SELECT :id, organization_id, bank_account_id, id, DATE '2027-01-20', 7_700,
                          :attack, 'HYPERLINK', md5(:attack) || md5(:attack), '{}', :now
                   FROM import_files
                   WHERE bank_account_id = :account AND kind = 'bank_statement' LIMIT 1"""
            ),
            {"id": uuid7(), "attack": ATTACK, "account": setup.account_id, "now": NOW},
        )
    return setup, reviewer


async def _request(
    client: httpx.AsyncClient, setup: Setup, period: str = "2027-01-01", **fields: Any
) -> httpx.Response:
    return await client.post(
        "/api/app/exports",
        json={
            "id": fields.pop("id", None) or client_id(),
            "bank_account_id": str(fields.pop("account", setup.account_id)),
            "period": period,
        },
        headers=xsrf_header(client),
    )


def _rows(content: bytes, sheet: str) -> list[tuple[Any, ...]]:
    workbook = load_workbook(BytesIO(content))
    return list(workbook[sheet].iter_rows(min_row=2, values_only=True))


async def test_an_analyst_downloads_the_month_with_who_confirmed_and_approved(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, books: tuple[Setup, Member]
) -> None:
    setup, reviewer = books
    export_id = client_id()
    async with signed_in(app, setup.member.email) as analyst:
        requested = await _request(analyst, setup, id=export_id)
        replay = await _request(analyst, setup, id=export_id)
        other_month = await _request(analyst, setup, "2027-02-01", id=export_id)
        early = await analyst.get(f"/api/app/exports/{export_id}/file")
        await work(worker_engine, FixedClock(NOW))
        state = (await analyst.get(f"/api/app/exports/{export_id}")).json()
        download = await analyst.get(f"/api/app/exports/{export_id}/file")

    assert (requested.status_code, replay.status_code) == (201, 200)
    assert requested.json()["job_id"] == export_id
    assert (other_month.status_code, other_month.json()["detail"]) == (409, "id_conflict")
    assert (early.status_code, early.json()["detail"]) == (409, "not_ready")
    assert state["status"] == "done"
    assert state["expires_at"].startswith("2027-02-04T15:00")
    assert download.status_code == 200
    assert download.headers["content-disposition"] == (
        'attachment; filename="conciliacion-2027-01.xlsx"'
    )
    [reconciled] = _rows(download.content, "Conciliados")
    names = {row.user_id: row.display_name for row in await _names(owner_engine, setup)}
    assert (reconciled[10], reconciled[12]) == (
        names[setup.member.user_id],
        names[reviewer.user_id],
    )
    [pending] = _rows(download.content, "Pendientes")
    assert pending[1] == f"'{ATTACK}"
    summary = dict(row[:2] for row in _rows(download.content, "Resumen") if row[0])
    assert summary["Estado del mes"] == "Abierto"
    async with owner_engine.connect() as connection:
        audited = await connection.scalar(
            text(
                """SELECT count(*) FROM audit_events
                   WHERE organization_id = :org AND action = 'export.requested'"""
            ),
            {"org": setup.organization_id},
        )
    assert audited == 1


async def _names(owner_engine: AsyncEngine, setup: Setup) -> Any:
    async with owner_engine.connect() as connection:
        return (
            await connection.execute(
                text(
                    """SELECT u.id AS user_id, u.display_name FROM users u
                       JOIN memberships m ON m.user_id = u.id WHERE m.organization_id = :org"""
                ),
                {"org": setup.organization_id},
            )
        ).all()


async def test_the_differences_sheet_shows_confirmed_differences_with_their_reason(
    app: FastAPI, worker_engine: AsyncEngine, books: tuple[Setup, Member]
) -> None:
    setup, reviewer = books
    async with signed_in(app, reviewer.email) as client:
        export_id = (await _request(client, setup, "2027-02-01")).json()["id"]
        await work(worker_engine, FixedClock(NOW))
        content = (await client.get(f"/api/app/exports/{export_id}/file")).content

    [difference] = _rows(content, "Diferencias")
    assert difference[7:9] == ("Comisión", "Confirmado")
    assert difference[12] is None
    assert _rows(content, "Conciliados") == []


async def test_an_export_expires_after_a_day_and_the_cleanup_deletes_it(
    app: FastAPI,
    database: DatabaseUrls,
    owner_engine: AsyncEngine,
    worker_engine: AsyncEngine,
    books: tuple[Setup, Member],
) -> None:
    setup, _ = books
    async with signed_in(app, setup.member.email) as analyst:
        export_id = (await _request(analyst, setup)).json()["id"]
    await work(worker_engine, FixedClock(NOW))
    later = build_app(database.for_role("concilia_app"), FixedClock(NOW + timedelta(hours=24)))
    try:
        async with signed_in(later, setup.member.email) as analyst:
            expired = await analyst.get(f"/api/app/exports/{export_id}/file")
    finally:
        await later.state.engine.dispose()
    async with worker_engine.begin() as connection:
        await connection.execute(
            text("SELECT app_cleanup(:now)"), {"now": NOW + timedelta(hours=24)}
        )
    async with owner_engine.connect() as connection:
        left = await connection.scalar(
            text("SELECT count(*) FROM exports WHERE job_id = :id"), {"id": export_id}
        )

    assert (expired.status_code, expired.json()["detail"]) == (410, "expired")
    assert left == 0


async def test_rerunning_export_period_stores_one_export(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, books: tuple[Setup, Member]
) -> None:
    setup, _ = books
    clock = FixedClock(NOW)
    async with signed_in(app, setup.member.email) as analyst:
        export_id = (await _request(analyst, setup)).json()["id"]
    runner = Runner(worker_engine, clock, handlers(worker_engine, clock))
    assert await runner.run_once()
    async with owner_engine.begin() as connection:
        await connection.execute(
            text("UPDATE jobs SET status = 'queued' WHERE id = :id"), {"id": export_id}
        )

    assert await runner.run_once()

    async with owner_engine.connect() as connection:
        exports = await connection.scalar(
            text("SELECT count(*) FROM exports WHERE job_id = :id"), {"id": export_id}
        )
        status = await connection.scalar(
            text("SELECT status FROM jobs WHERE id = :id"), {"id": export_id}
        )
    assert (exports, status) == (1, "done")


async def test_only_analysts_and_reviewers_export(
    app: FastAPI, owner_engine: AsyncEngine, books: tuple[Setup, Member]
) -> None:
    setup, _ = books
    admin = await add_member(owner_engine, NOW, setup.organization_id, ["admin"])
    async with signed_in(app, admin.email) as client:
        refused = await _request(client, setup)

    assert (refused.status_code, refused.json()["detail"]) == (403, "role_required")


async def test_exports_stay_inside_their_organization(
    app: FastAPI, owner_engine: AsyncEngine, books: tuple[Setup, Member]
) -> None:
    setup, _ = books
    stranger = await statement_setup(owner_engine, ["analyst"])
    async with signed_in(app, setup.member.email) as analyst:
        export_id = (await _request(analyst, setup)).json()["id"]
    async with signed_in(app, stranger.member.email) as client:
        foreign_account = await _request(client, setup)
        seen = await client.get(f"/api/app/exports/{export_id}")
        file = await client.get(f"/api/app/exports/{export_id}/file")
        taken_id = await _request(client, stranger, id=export_id)

    assert (foreign_account.status_code, foreign_account.json()["detail"]) == (404, "not_found")
    assert (seen.status_code, file.status_code) == (404, 404)
    assert (taken_id.status_code, taken_id.json()["detail"]) == (409, "id_conflict")
