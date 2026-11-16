from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid7

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.support.api import build_app, signed_in, xsrf_header
from tests.support.clock import FixedClock
from tests.support.database import DatabaseUrls
from tests.support.imports import (
    NOW,
    RECEIVABLES,
    Setup,
    client_id,
    receivables_profile,
    statement_setup,
    upload,
    work,
)

pytestmark = pytest.mark.anyio

STATEMENT = (
    b"Fecha;Detalle;Importe\n"
    b"05/01/2027;PAGO FACT F001-123;1.180,00\n"
    b"06/01/2027;COMISION;-12,50\n"
    b"10/01/2027;DEPOSITO VARIOS;75,00\n"
    b"12/01/2027;ABONO SIN REFERENCIA;33,00\n"
    b"07/02/2027;TRANSF CLIENTE;500,00\n"
)
JANUARY = "2027-01-01"


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
    **kwargs: Any,
) -> None:
    response = await upload(client, setup, content, **kwargs)
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
        await _import(client, setup, worker_engine, clock, RECEIVABLES, profile_id=profile_id)
        for period in (JANUARY, "2027-02-01"):
            await client.post(
                "/api/app/engine-runs",
                json={
                    "id": client_id(),
                    "bank_account_id": str(setup.account_id),
                    "period": period,
                },
                headers=xsrf_header(client),
            )
            await work(worker_engine, clock)
    return setup


def _query(setup: Setup, **params: Any) -> dict[str, Any]:
    return {"bank_account_id": str(setup.account_id), "period": JANUARY, **params}


async def test_periods_and_counts_describe_the_month(app: FastAPI, setup: Setup) -> None:
    async with signed_in(app, setup.member.email) as client:
        periods = (
            await client.get(
                "/api/app/inbox/periods", params={"bank_account_id": str(setup.account_id)}
            )
        ).json()
        counts = (await client.get("/api/app/inbox/counts", params=_query(setup))).json()

    assert periods == [
        {"period": "2027-02-01", "closed": False, "credits": 1},
        {"period": "2027-01-01", "closed": False, "credits": 3},
    ]
    assert counts == {"free": 2, "proposed": 1, "confirmed": 0, "approved": 0}


async def test_free_credits_are_paged_by_date_and_filtered_by_amount(
    app: FastAPI, setup: Setup
) -> None:
    async with signed_in(app, setup.member.email) as client:
        first = (await client.get("/api/app/inbox/credits", params=_query(setup, limit=1))).json()
        second = (
            await client.get(
                "/api/app/inbox/credits",
                params=_query(setup, limit=1, after=first["next_cursor"]),
            )
        ).json()
        back = (
            await client.get(
                "/api/app/inbox/credits",
                params=_query(setup, limit=1, before=second["previous_cursor"]),
            )
        ).json()
        large = (
            await client.get("/api/app/inbox/credits", params=_query(setup, min_amount_cents=5000))
        ).json()

    def descriptions(page: dict[str, Any]) -> list[str]:
        return [credit["description"] for credit in page["credits"]]

    assert (descriptions(first), first["has_next"]) == (["DEPOSITO VARIOS"], True)
    assert (descriptions(second), second["has_previous"], second["has_next"]) == (
        ["ABONO SIN REFERENCIA"],
        True,
        False,
    )
    assert (descriptions(back), back["has_previous"]) == (["DEPOSITO VARIOS"], False)
    assert descriptions(large) == ["DEPOSITO VARIOS"]


async def test_matches_are_listed_by_status_with_filters(
    app: FastAPI, owner_engine: AsyncEngine, setup: Setup
) -> None:
    async with signed_in(app, setup.member.email) as client:

        async def matches(**params: Any) -> list[dict[str, Any]]:
            response = await client.get("/api/app/matches", params=_query(setup, **params))
            rows: list[dict[str, Any]] = response.json()["matches"]
            return rows

        proposed = await matches()
        by_rule = await matches(rule="R6")
        by_score = await matches(min_score=90)
        by_amount = await matches(min_amount_cents=200_000)
        async with owner_engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO match_decisions (id, organization_id, match_id, action,
                                                    decided_by, decided_at)
                       VALUES (:id, :org, :match, 'confirm', :user, :now)"""
                ),
                {
                    "id": uuid7(),
                    "org": setup.organization_id,
                    "match": proposed[0]["id"],
                    "user": setup.member.user_id,
                    "now": NOW,
                },
            )
        still_proposed = await matches()
        confirmed = await matches(status="confirmed")

    assert [{**row, "id": None} for row in proposed] == [
        {
            "id": None,
            "source": "engine",
            "rule": "R1",
            "score": 100,
            "status": "proposed",
            "booked_on": "2027-01-05",
            "description": "PAGO FACT F001-123",
            "documents": ["F001-00000123"],
            "customers": ["Comercial Andina SAC"],
            "credits_cents": 118_000,
            "applied_cents": 118_000,
            "difference_cents": 0,
        }
    ]
    assert (by_rule, len(by_score), by_amount) == ([], 1, [])
    assert still_proposed == []
    assert [row["status"] for row in confirmed] == ["confirmed"]


async def test_a_match_detail_shows_items_balances_and_decisions(
    app: FastAPI, owner_engine: AsyncEngine, setup: Setup
) -> None:
    async with signed_in(app, setup.member.email) as client:
        [row] = (await client.get("/api/app/matches", params=_query(setup))).json()["matches"]
        async with owner_engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO match_decisions (id, organization_id, match_id, action,
                                                    decided_by, decided_at)
                       VALUES (:id, :org, :match, 'confirm', :user, :now)"""
                ),
                {
                    "id": uuid7(),
                    "org": setup.organization_id,
                    "match": row["id"],
                    "user": setup.member.user_id,
                    "now": NOW,
                },
            )
        detail = (await client.get(f"/api/app/matches/{row['id']}")).json()

    assert (detail["status"], detail["rule"], detail["score"]) == ("confirmed", "R1", 100)
    assert detail["explanation"].startswith("La descripción menciona F001-123")
    assert [credit["amount_cents"] for credit in detail["credits"]] == [118_000]
    assert [
        (item["doc_number"], item["applied_cents"], item["available_cents"])
        for item in detail["receivables"]
    ] == [("F001-00000123", 118_000, 0)]
    assert [(d["action"], d["decided_by"]) for d in detail["decisions"]] == [
        ("confirm", "Test user")
    ]
    assert (detail["credits_cents"], detail["applied_cents"], detail["difference_cents"]) == (
        118_000,
        118_000,
        0,
    )


async def test_the_inbox_validates_its_inputs(app: FastAPI, setup: Setup) -> None:
    async with signed_in(app, setup.member.email) as client:
        mid_month = await client.get(
            "/api/app/inbox/counts", params=_query(setup, period="2027-01-15")
        )
        bad_cursor = await client.get("/api/app/matches", params=_query(setup, after="nope"))
        bad_status = await client.get("/api/app/matches", params=_query(setup, status="discarded"))
        unknown = await client.get(f"/api/app/matches/{uuid7()}")

    assert (mid_month.status_code, mid_month.json()["detail"]) == (422, "invalid_period")
    assert (bad_cursor.status_code, bad_cursor.json()["detail"]) == (422, "invalid_cursor")
    assert bad_status.status_code == 422
    assert (unknown.status_code, unknown.json()["detail"]) == (404, "not_found")


async def test_the_inbox_stays_inside_its_organization(
    app: FastAPI, owner_engine: AsyncEngine, setup: Setup
) -> None:
    other = await statement_setup(owner_engine)
    async with signed_in(app, setup.member.email) as client:
        [row] = (await client.get("/api/app/matches", params=_query(setup))).json()["matches"]
    async with signed_in(app, other.member.email) as client:
        periods = await client.get(
            "/api/app/inbox/periods", params={"bank_account_id": str(setup.account_id)}
        )
        credits = await client.get("/api/app/inbox/credits", params=_query(setup))
        detail = await client.get(f"/api/app/matches/{row['id']}")

    assert [periods.status_code, credits.status_code, detail.status_code] == [404, 404, 404]
