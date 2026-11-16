import asyncio
import json
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import uuid7

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from concilia.ai.application.llm import LlmError
from concilia.ai.infrastructure.clients import LlmClients
from concilia.ai.infrastructure.fake_llm import FakeLlmClient
from concilia.shared.infrastructure.jobs import Runner
from concilia.shared.kernel.clock import lima_day_start
from concilia.worker import handlers
from tests.support.ai import (
    CLOCK,
    ai_app,
    answer,
    ask_ai,
    credit_of,
    imported_books,
    model_suggestion,
    run_ai_jobs,
)
from tests.support.api import add_member, build_app, signed_in
from tests.support.database import DatabaseUrls
from tests.support.imports import NOW, Setup, client_id, statement_setup

pytestmark = pytest.mark.anyio


@pytest.fixture
async def books(
    database: DatabaseUrls, owner_engine: AsyncEngine, worker_engine: AsyncEngine
) -> Setup:
    return await imported_books(database, owner_engine, worker_engine)


async def _asked_and_answered(
    database: DatabaseUrls,
    owner_engine: AsyncEngine,
    worker_engine: AsyncEngine,
    setup: Setup,
    answer: Callable[[str], str],
) -> tuple[dict[str, Any], FakeLlmClient]:
    real = FakeLlmClient(answer)
    llm = LlmClients(real=real)
    credit = await credit_of(owner_engine, setup, 50_000)
    async with ai_app(database, llm) as app, signed_in(app, setup.member.email) as analyst:
        requested = await ask_ai(analyst, credit)
        assert requested.status_code == 201, requested.text
        await run_ai_jobs(worker_engine, llm)
        view = (await analyst.get(f"/api/app/ai/suggestions/{requested.json()['id']}")).json()
    return view, real


async def test_suggestions_are_validated_and_recomputed_by_the_server(
    database: DatabaseUrls, owner_engine: AsyncEngine, worker_engine: AsyncEngine, books: Setup
) -> None:
    view, real = await _asked_and_answered(
        database,
        owner_engine,
        worker_engine,
        books,
        answer(model_suggestion(["C1"], [("C1", 99_999_999)])),
    )

    assert (view["status"], view["valid"]) == ("done", True)
    [suggestion] = view["suggestions"]
    assert [(r["doc_number"], r["applied_cents"]) for r in suggestion["receivables"]] == [
        ("F001-124", 50_000)
    ]
    assert (suggestion["difference_cents"], suggestion["recomputed"]) == (0, True)
    [sent] = real.calls
    assert set(json.loads(sent)["abono"]) == {"fecha", "monto_centimos", "descripcion"}
    assert suggestion["receivables"][0]["receivable_id"] not in sent


async def test_an_output_that_does_not_validate_is_stored_as_invalid_and_shows_nothing(
    database: DatabaseUrls, owner_engine: AsyncEngine, worker_engine: AsyncEngine, books: Setup
) -> None:
    view, _ = await _asked_and_answered(
        database, owner_engine, worker_engine, books, lambda _user: "Claro, aquí va: C1"
    )

    assert (view["status"], view["valid"], view["suggestions"]) == ("done", False, [])
    async with owner_engine.connect() as connection:
        stored = (
            await connection.execute(
                text(
                    "SELECT valid, server_applied, response FROM ai_suggestions WHERE job_id = :id"
                ),
                {"id": view["id"]},
            )
        ).one()
    assert (stored.valid, stored.server_applied, stored.response) == (
        False,
        None,
        "Claro, aquí va: C1",
    )


async def test_invented_aliases_are_dropped(
    database: DatabaseUrls, owner_engine: AsyncEngine, worker_engine: AsyncEngine, books: Setup
) -> None:
    view, _ = await _asked_and_answered(
        database,
        owner_engine,
        worker_engine,
        books,
        answer(
            model_suggestion(["C9"], [("C9", 50_000)]),
            model_suggestion(["C1", "C7"], [("C1", 10_000), ("C7", 40_000)]),
        ),
    )

    [kept] = view["suggestions"]
    assert [r["alias"] for r in kept["receivables"]] == ["C1"]
    assert kept["receivables"][0]["applied_cents"] == 50_000


async def test_a_burst_of_requests_stops_at_the_organization_daily_limit(
    database: DatabaseUrls, owner_engine: AsyncEngine, books: Setup
) -> None:
    async with owner_engine.begin() as connection:
        for _ in range(48):
            await connection.execute(
                text(
                    """INSERT INTO jobs (id, organization_id, kind, payload, run_after, created_by,
                                         created_at, status)
                       VALUES (:id, :org, 'ai_suggest', '{}', :now, :user, :now, 'done')"""
                ),
                {
                    "id": uuid7(),
                    "org": books.organization_id,
                    "now": NOW,
                    "user": books.member.user_id,
                },
            )
    credit = await credit_of(owner_engine, books, 50_000)
    llm = LlmClients(real=FakeLlmClient())
    async with (
        ai_app(database, llm, ai_global_daily_limit=1_000_000) as app,
        signed_in(app, books.member.email) as analyst,
    ):
        responses = await asyncio.gather(*(ask_ai(analyst, credit) for _ in range(5)))

    codes = sorted(r.status_code for r in responses)
    assert codes == [201, 201, 429, 429, 429]
    assert {r.json().get("detail") for r in responses if r.status_code == 429} == {"ai_daily_limit"}


async def test_a_burst_of_requests_stops_at_the_global_daily_limit(
    database: DatabaseUrls, owner_engine: AsyncEngine, worker_engine: AsyncEngine, books: Setup
) -> None:
    today = NOW.date()
    async with worker_engine.connect() as connection:
        used = await connection.scalar(
            text("SELECT app_ai_usage_today(:since, :until)"),
            {"since": lima_day_start(today), "until": lima_day_start(today + timedelta(days=1))},
        )
    credit = await credit_of(owner_engine, books, 50_000)
    llm = LlmClients(real=FakeLlmClient())
    async with (
        ai_app(database, llm, ai_global_daily_limit=int(used or 0) + 2) as app,
        signed_in(app, books.member.email) as analyst,
    ):
        responses = await asyncio.gather(*(ask_ai(analyst, credit) for _ in range(4)))

    assert sorted(r.status_code for r in responses) == [201, 201, 429, 429]
    assert {r.json().get("detail") for r in responses if r.status_code == 429} == {
        "ai_global_limit"
    }


async def test_without_ai_enabled_the_endpoints_do_not_exist(
    database: DatabaseUrls, owner_engine: AsyncEngine, books: Setup
) -> None:
    credit = await credit_of(owner_engine, books, 50_000)
    app = build_app(database.for_role("concilia_app"), CLOCK, llm=LlmClients(FakeLlmClient()))
    try:
        async with signed_in(app, books.member.email) as analyst:
            response = await ask_ai(analyst, credit)
    finally:
        await app.state.engine.dispose()

    assert response.status_code == 404


async def test_without_a_provider_key_a_regular_organization_cannotask_ai(
    database: DatabaseUrls, owner_engine: AsyncEngine, books: Setup
) -> None:
    credit = await credit_of(owner_engine, books, 50_000)
    async with (
        ai_app(database, LlmClients(real=None)) as app,
        signed_in(app, books.member.email) as analyst,
    ):
        response = await ask_ai(analyst, credit)

    assert (response.status_code, response.json()["detail"]) == (409, "ai_unavailable")


async def test_a_credit_in_a_closed_month_or_unknown_is_not_free(
    database: DatabaseUrls, owner_engine: AsyncEngine, books: Setup
) -> None:
    reviewer = await add_member(owner_engine, NOW, books.organization_id, ["reviewer"])
    async with owner_engine.begin() as connection:
        await connection.execute(
            text(
                """INSERT INTO period_events (id, organization_id, bank_account_id, period, action,
                                             decided_by, decided_at)
                   VALUES (:id, :org, :account, DATE '2027-01-01', 'close', :user, :now)"""
            ),
            {
                "id": uuid7(),
                "org": books.organization_id,
                "account": books.account_id,
                "user": reviewer.user_id,
                "now": NOW,
            },
        )
    january = await credit_of(owner_engine, books, 118_000)
    llm = LlmClients(real=FakeLlmClient())
    async with ai_app(database, llm) as app:
        async with signed_in(app, books.member.email) as analyst:
            closed = await ask_ai(analyst, january)
            unknown = await ask_ai(analyst, str(uuid7()))
        async with signed_in(app, reviewer.email) as client:
            not_analyst = await ask_ai(client, january)

    assert (closed.status_code, closed.json()["detail"]) == (409, "credit_not_free")
    assert (unknown.status_code, unknown.json()["detail"]) == (409, "credit_not_free")
    assert (not_analyst.status_code, not_analyst.json()["detail"]) == (403, "role_required")


async def test_requests_are_idempotent_audited_and_stay_inside_their_organization(
    database: DatabaseUrls, owner_engine: AsyncEngine, books: Setup
) -> None:
    stranger = await statement_setup(owner_engine, ["analyst"])
    credit = await credit_of(owner_engine, books, 50_000)
    request_id = client_id()
    llm = LlmClients(real=FakeLlmClient())
    async with ai_app(database, llm) as app:
        async with signed_in(app, books.member.email) as analyst:
            first = await ask_ai(analyst, credit, request_id)
            again = await ask_ai(analyst, credit, request_id)
        async with signed_in(app, stranger.member.email) as client:
            seen = await client.get(f"/api/app/ai/suggestions/{request_id}")
            foreign_credit = await ask_ai(client, credit)
            taken_id = await ask_ai(client, credit, request_id)

    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json() == first.json()
    assert seen.status_code == 404
    assert (foreign_credit.status_code, foreign_credit.json()["detail"]) == (409, "credit_not_free")
    assert taken_id.status_code == 409
    async with owner_engine.connect() as connection:
        audited = await connection.scalar(
            text(
                """SELECT count(*) FROM audit_events
                   WHERE organization_id = :org AND action = 'ai_suggestion.requested'"""
            ),
            {"org": books.organization_id},
        )
    assert audited == 1


async def test_rerunning_ai_suggest_calls_the_provider_once_and_stores_onesuggestion(
    database: DatabaseUrls, owner_engine: AsyncEngine, worker_engine: AsyncEngine, books: Setup
) -> None:
    real = FakeLlmClient(answer(model_suggestion(["C1"], None)))
    llm = LlmClients(real=real)
    credit = await credit_of(owner_engine, books, 50_000)
    async with ai_app(database, llm) as app, signed_in(app, books.member.email) as analyst:
        request_id = (await ask_ai(analyst, credit)).json()["id"]
    runner = Runner(worker_engine, CLOCK, handlers(worker_engine, CLOCK, llm))
    assert await runner.run_once()
    async with owner_engine.begin() as connection:
        await connection.execute(
            text("UPDATE jobs SET status = 'queued' WHERE id = :id"), {"id": request_id}
        )

    assert await runner.run_once()

    async with owner_engine.connect() as connection:
        stored = await connection.scalar(
            text("SELECT count(*) FROM ai_suggestions WHERE job_id = :id"), {"id": request_id}
        )
    assert (stored, len(real.calls)) == (1, 1)


async def test_a_provider_failure_stores_nothing_and_leaves_its_code_on_the_job(
    database: DatabaseUrls, owner_engine: AsyncEngine, worker_engine: AsyncEngine, books: Setup
) -> None:
    def exhausted(_user: str) -> str:
        raise LlmError("ai_budget_exhausted", retry=False)

    llm = LlmClients(real=FakeLlmClient(exhausted))
    credit = await credit_of(owner_engine, books, 50_000)
    async with ai_app(database, llm) as app, signed_in(app, books.member.email) as analyst:
        request_id = (await ask_ai(analyst, credit)).json()["id"]
        await run_ai_jobs(worker_engine, llm)
        view = (await analyst.get(f"/api/app/ai/suggestions/{request_id}")).json()

    assert (view["status"], view["error_code"], view["valid"]) == (
        "failed",
        "ai_budget_exhausted",
        None,
    )


async def test_a_demo_never_reaches_the_provider_nor_counts_for_the_limits(
    database: DatabaseUrls, worker_engine: AsyncEngine
) -> None:
    real = FakeLlmClient(answer(model_suggestion(["C1"], None)))
    llm = LlmClients(real=real)
    async with ai_app(database, llm, ai_global_daily_limit=0) as app:
        transport = httpx.ASGITransport(app=app, client=("203.0.113.90", 50_000))
        async with httpx.AsyncClient(
            transport=transport, base_url="https://test", headers={"Origin": "https://test"}
        ) as visitor:
            assert (await visitor.post("/api/public/demo")).status_code == 201
            [account] = (await visitor.get("/api/app/bank-accounts")).json()
            credits = (
                await visitor.get(
                    "/api/app/inbox/credits",
                    params={"bank_account_id": account["id"], "period": "2026-11-01", "limit": 1},
                )
            ).json()["credits"]
            requested = await ask_ai(visitor, credits[0]["id"])
            await run_ai_jobs(worker_engine, llm)
            view = (await visitor.get(f"/api/app/ai/suggestions/{requested.json()['id']}")).json()

    assert requested.status_code == 201
    assert (view["status"], view["valid"], view["suggestions"]) == ("done", True, [])
    assert view["no_match_reason"] == "Sin sugerencias en la demo para este abono."
    assert real.calls == []
