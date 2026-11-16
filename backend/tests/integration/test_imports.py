from collections.abc import AsyncIterator
from datetime import date
from typing import Any
from uuid import uuid7

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from concilia.imports.domain.statement import StatementLine, fingerprints
from concilia.shared.infrastructure.jobs import enqueue
from tests.support.api import build_app, signed_in, xsrf_header
from tests.support.clock import FixedClock
from tests.support.database import DatabaseUrls
from tests.support.imports import (
    NOW,
    STATEMENT,
    client_id,
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


async def test_an_upload_is_previewed_by_the_worker(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    setup = await statement_setup(owner_engine)
    async with signed_in(app, setup.member.email) as client:
        uploaded = await upload(client, setup, filename="C:\\Descargas\\enero.csv")
        assert uploaded.status_code == 201
        body = uploaded.json()
        assert body["file"]["status"] == "uploaded"
        assert body["file"]["filename"] == "enero.csv"
        assert body["duplicate_of"] is None

        assert await work(worker_engine, clock) == 1

        summary = (await client.get(f"/api/app/imports/{body['file']['id']}")).json()
        ok = (await client.get(f"/api/app/imports/{body['file']['id']}/rows")).json()
        errors = (
            await client.get(f"/api/app/imports/{body['file']['id']}/rows?status=error")
        ).json()
        job = (await client.get(f"/api/app/jobs/{body['job_id']}")).json()

    assert summary["file"]["status"] == "previewed"
    assert summary["file"]["row_count"] == 4
    assert summary["counts"] == {
        "ok": 3,
        "error": 1,
        "duplicate": 0,
        "closed_period": 0,
        "conflict": 0,
    }
    assert [(r["row_number"], r["amount_cents"]) for r in ok["rows"]] == [
        (2, 118_000),
        (3, -1_250),
        (4, 50_000),
    ]
    assert errors["rows"] == [
        {
            "row_number": 5,
            "status": "error",
            "error_code": "missing_amount",
            "cells": ["08/02/2027", "SIN MONTO", ""],
        }
    ]
    assert (job["status"], job["progress"]) == ("done", 100)


async def test_rows_already_imported_or_in_closed_periods_are_flagged(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    setup = await statement_setup(owner_engine)
    line = StatementLine(2, date(2027, 1, 5), 118_000, "PAGO FACT F001-123", None)
    [fingerprint] = fingerprints(setup.account_id, [line])
    async with owner_engine.begin() as connection:
        await connection.execute(
            text(
                """INSERT INTO import_files (id, organization_id, kind, bank_account_id,
                                             import_profile_id, profile_snapshot, filename, sha256,
                                             size_bytes, content, status, created_by, created_at)
                   VALUES (:file, :org, 'bank_statement', :account, :profile, '{}', 'old.csv',
                           repeat('c', 64), 1, 'x', 'confirmed', :user, :now)"""
            ),
            {
                "file": (old_file := uuid7()),
                "org": setup.organization_id,
                "account": setup.account_id,
                "profile": setup.profile_id,
                "user": setup.member.user_id,
                "now": NOW,
            },
        )
        await connection.execute(
            text(
                """INSERT INTO bank_movements (id, organization_id, bank_account_id, import_file_id,
                                               booked_on, amount_cents, description,
                                               description_norm, fingerprint, doc_refs, created_at)
                   VALUES (:id, :org, :account, :file, '2027-01-05', 118000, 'PAGO FACT F001-123',
                           'PAGO FACT F001 123', :fingerprint, '{F001-123}', :now)"""
            ),
            {
                "id": uuid7(),
                "org": setup.organization_id,
                "account": setup.account_id,
                "file": old_file,
                "fingerprint": fingerprint,
                "now": NOW,
            },
        )
        await connection.execute(
            text(
                """INSERT INTO period_events (id, organization_id, bank_account_id, period, action,
                                              decided_by, decided_at)
                   VALUES (:id, :org, :account, '2027-01-01', 'close', :user, :now)"""
            ),
            {
                "id": uuid7(),
                "org": setup.organization_id,
                "account": setup.account_id,
                "user": setup.member.user_id,
                "now": NOW,
            },
        )
    async with signed_in(app, setup.member.email) as client:
        file_id = (await upload(client, setup)).json()["file"]["id"]
        await work(worker_engine, clock)
        counts = (await client.get(f"/api/app/imports/{file_id}")).json()["counts"]

    assert counts == {"ok": 1, "error": 1, "duplicate": 1, "closed_period": 1, "conflict": 0}


async def test_uploads_are_idempotent_on_the_client_id(
    app: FastAPI, owner_engine: AsyncEngine
) -> None:
    setup = await statement_setup(owner_engine)
    other = await statement_setup(owner_engine)
    file_id = client_id()
    async with signed_in(app, setup.member.email) as client:
        first = await upload(client, setup, file_id=file_id)
        replay = await upload(client, setup, file_id=file_id)
        changed = await upload(client, setup, STATEMENT + b"09/02/2027;X;1,00\n", file_id)
    async with signed_in(app, other.member.email) as client:
        elsewhere = await upload(client, other, file_id=file_id)

    assert (first.status_code, replay.status_code) == (201, 200)
    assert replay.json()["job_id"] is None
    assert (changed.status_code, elsewhere.status_code) == (409, 409)


@pytest.mark.parametrize(
    ("content", "code", "detail"),
    [
        (b"PK\x03\x04 not a workbook", 422, "unreadable_file"),
        (b"Fecha;Detalle\x00;Importe", 422, "unreadable_file"),
        (b"", 422, "empty_file"),
        (b"x" * (5 * 1024 * 1024 + 1), 413, "file_too_large"),
    ],
)
async def test_the_content_is_checked_on_upload(
    app: FastAPI, owner_engine: AsyncEngine, content: bytes, code: int, detail: str
) -> None:
    setup = await statement_setup(owner_engine)
    async with signed_in(app, setup.member.email) as client:
        response = await upload(client, setup, content)

    assert (response.status_code, response.json()["detail"]) == (code, detail)


async def test_only_analysts_upload_and_only_with_their_own_profiles(
    app: FastAPI, owner_engine: AsyncEngine
) -> None:
    setup = await statement_setup(owner_engine)
    admin_only = await statement_setup(owner_engine, ["admin"])
    other = await statement_setup(owner_engine)
    async with signed_in(app, admin_only.member.email) as client:
        forbidden = await upload(client, admin_only)
    async with signed_in(app, other.member.email) as client:
        foreign = await upload(client, setup)
    async with owner_engine.begin() as connection:
        await connection.execute(
            text("UPDATE import_profiles SET archived_at = :now WHERE id = :id"),
            {"now": NOW, "id": setup.profile_id},
        )
    async with signed_in(app, setup.member.email) as client:
        archived = await upload(client, setup)

    assert (forbidden.status_code, forbidden.json()["detail"]) == (403, "role_required")
    assert (foreign.status_code, archived.status_code) == (404, 404)


async def test_an_unreadable_layout_fails_the_file(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    setup = await statement_setup(owner_engine)
    async with signed_in(app, setup.member.email) as client:
        file_id = (await upload(client, setup, b"Fecha;Concepto\n05/01/2027;X\n")).json()["file"][
            "id"
        ]
        await work(worker_engine, clock)
        summary = (await client.get(f"/api/app/imports/{file_id}")).json()

    assert (summary["file"]["status"], summary["file"]["error_code"]) == (
        "failed",
        "missing_columns",
    )


async def test_previews_are_paged_by_row_number(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    setup = await statement_setup(owner_engine)
    content = ("Fecha;Detalle;Importe\n" + "05/01/2027;PAGO;1,00\n" * 120).encode()
    async with signed_in(app, setup.member.email) as client:
        file_id = (await upload(client, setup, content)).json()["file"]["id"]
        await work(worker_engine, clock)
        url = f"/api/app/imports/{file_id}/rows"
        first = (await client.get(url)).json()
        second = (await client.get(f"{url}?after=51")).json()
        back = (await client.get(f"{url}?before=52")).json()
        last = (await client.get(f"{url}?after=101")).json()

    def numbers(page: dict[str, Any]) -> list[int]:
        return [row["row_number"] for row in page["rows"]]

    assert (numbers(first)[0], numbers(first)[-1]) == (2, 51)
    assert (first["has_previous"], first["has_next"]) == (False, True)
    assert numbers(second)[0] == 52
    assert numbers(back) == numbers(first)
    assert (back["has_previous"], back["has_next"]) == (False, True)
    assert (numbers(last)[-1], last["has_next"]) == (121, False)


async def test_discarding_a_preview_removes_its_rows(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    setup = await statement_setup(owner_engine)
    async with signed_in(app, setup.member.email) as client:
        uploaded = (await upload(client, setup)).json()
        file_id = uploaded["file"]["id"]
        too_early = await client.post(
            f"/api/app/imports/{file_id}/discard", headers=xsrf_header(client)
        )
        await work(worker_engine, clock)
        discarded = [
            await client.post(f"/api/app/imports/{file_id}/discard", headers=xsrf_header(client))
            for _ in range(2)
        ]
        summary = (await client.get(f"/api/app/imports/{file_id}")).json()

    assert (too_early.status_code, too_early.json()["detail"]) == (409, "wrong_state")
    assert [response.status_code for response in discarded] == [204, 204]
    assert summary["file"]["status"] == "discarded"
    assert sum(summary["counts"].values()) == 0
    async with owner_engine.connect() as connection:
        actions = list(
            await connection.scalars(
                text("SELECT action FROM audit_events WHERE organization_id = :org ORDER BY seq"),
                {"org": setup.organization_id},
            )
        )
    assert actions == ["import.uploaded", "import.discarded"]


async def test_rerunning_parse_import_does_not_duplicate_rows(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    setup = await statement_setup(owner_engine)
    async with signed_in(app, setup.member.email) as client:
        file_id = (await upload(client, setup)).json()["file"]["id"]
    async with owner_engine.begin() as connection:
        await connection.execute(
            text("UPDATE import_files SET status = 'parsing' WHERE id = :id"), {"id": file_id}
        )
    await work(worker_engine, clock)
    async with worker_engine.begin() as connection:
        await enqueue(
            connection,
            job_id=uuid7(),
            kind="parse_import",
            now=NOW,
            organization_id=setup.organization_id,
            payload={"import_file_id": file_id},
        )
    assert await work(worker_engine, clock) == 1

    async with owner_engine.connect() as connection:
        rows = await connection.scalar(
            text("SELECT count(*) FROM import_rows WHERE import_file_id = :id"), {"id": file_id}
        )
    assert rows == 4


async def test_imports_and_jobs_of_another_organization_are_invisible(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    setup = await statement_setup(owner_engine)
    other = await statement_setup(owner_engine)
    async with signed_in(app, setup.member.email) as client:
        uploaded = (await upload(client, setup)).json()
    await work(worker_engine, clock)
    file_id = uploaded["file"]["id"]
    async with signed_in(app, other.member.email) as client:
        responses = [
            await client.get(f"/api/app/imports/{file_id}"),
            await client.get(f"/api/app/imports/{file_id}/rows"),
            await client.post(f"/api/app/imports/{file_id}/discard", headers=xsrf_header(client)),
            await client.get(f"/api/app/jobs/{uploaded['job_id']}"),
        ]

    assert [response.status_code for response in responses] == [404, 404, 404, 404]
