import asyncio
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from concilia.ai.infrastructure.clients import LlmClients
from concilia.ai.infrastructure.fake_llm import FakeLlmClient
from tests.support.ai import (
    ai_app,
    answer,
    ask_ai,
    credit_of,
    imported_books,
    model_suggestion,
    run_ai_jobs,
)
from tests.support.api import add_member, signed_in, xsrf_header
from tests.support.database import DatabaseUrls
from tests.support.imports import NOW, Setup, client_id, statement_setup

pytestmark = pytest.mark.anyio

TWO_WAYS = answer(
    model_suggestion(["C1"], [("C1", 50_000)]),
    model_suggestion(["C2"], [("C2", 50_000)]),
)


@pytest.fixture
async def books(
    database: DatabaseUrls, owner_engine: AsyncEngine, worker_engine: AsyncEngine
) -> Setup:
    return await imported_books(database, owner_engine, worker_engine)


async def _decide(
    client: httpx.AsyncClient, suggestion_id: str, index: int, action: str, **fields: Any
) -> httpx.Response:
    return await client.post(
        f"/api/app/ai/suggestions/{suggestion_id}/decisions",
        json={
            "id": fields.pop("id", None) or client_id(),
            "index": index,
            "action": action,
            **fields,
        },
        headers=xsrf_header(client),
    )


async def _suggested(
    client: httpx.AsyncClient,
    owner_engine: AsyncEngine,
    worker_engine: AsyncEngine,
    setup: Setup,
    llm: LlmClients,
) -> str:
    requested = await ask_ai(client, await credit_of(owner_engine, setup, 50_000))
    await run_ai_jobs(worker_engine, llm)
    suggestion_id: str = requested.json()["id"]
    return suggestion_id


async def test_accepting_creates_a_proposed_ai_match_that_follows_the_normal_flow(
    database: DatabaseUrls, owner_engine: AsyncEngine, worker_engine: AsyncEngine, books: Setup
) -> None:
    reviewer = await add_member(owner_engine, NOW, books.organization_id, ["reviewer"])
    llm = LlmClients(real=FakeLlmClient(TWO_WAYS))
    async with ai_app(database, llm) as app:
        async with signed_in(app, books.member.email) as analyst:
            suggestion_id = await _suggested(analyst, owner_engine, worker_engine, books, llm)
            accepted = await _decide(analyst, suggestion_id, 0, "accept")
            second = await _decide(analyst, suggestion_id, 1, "accept")
            view = (await analyst.get(f"/api/app/ai/suggestions/{suggestion_id}")).json()
            match_id = accepted.json()["match_id"]
            detail = (await analyst.get(f"/api/app/matches/{match_id}")).json()
            confirmed = await analyst.post(
                f"/api/app/matches/{match_id}/decisions",
                json={"id": client_id(), "action": "confirm"},
                headers=xsrf_header(analyst),
            )
        async with signed_in(app, reviewer.email) as client:
            approved = await client.post(
                f"/api/app/matches/{match_id}/decisions",
                json={"id": client_id(), "action": "approve"},
                headers=xsrf_header(client),
            )

    assert accepted.status_code == 201
    assert (second.status_code, second.json()["detail"]) == (409, "credit_not_free")
    assert view["suggestions"][0]["decision"]["action"] == "accept"
    assert view["suggestions"][1]["decision"] is None
    assert (detail["source"], detail["status"]) == ("ai", "proposed")
    assert detail["explanation"] == "El monto coincide con el saldo de F001-124."
    assert [r["applied_cents"] for r in detail["receivables"]] == [50_000]
    assert (confirmed.status_code, approved.status_code) == (201, 201)
    async with owner_engine.connect() as connection:
        actions = list(
            await connection.scalars(
                text(
                    """SELECT action || coalesce(':' || (metadata->>'source'), '')
                       FROM audit_events
                       WHERE organization_id = :org AND entity IN ('ai_suggestion', 'match')
                       ORDER BY seq"""
                ),
                {"org": books.organization_id},
            )
        )
    assert actions[:3] == ["ai_suggestion.requested", "match.created:ai", "ai_suggestion.accepted"]


async def test_rejecting_needs_a_reason_and_each_suggestion_is_decided_once(
    database: DatabaseUrls, owner_engine: AsyncEngine, worker_engine: AsyncEngine, books: Setup
) -> None:
    llm = LlmClients(real=FakeLlmClient(TWO_WAYS))
    decision_id = client_id()
    async with ai_app(database, llm) as app, signed_in(app, books.member.email) as analyst:
        suggestion_id = await _suggested(analyst, owner_engine, worker_engine, books, llm)
        no_reason = await _decide(analyst, suggestion_id, 1, "reject", reason="  ")
        rejected = await _decide(
            analyst,
            suggestion_id,
            1,
            "reject",
            reason="Ese cobro es de otra cuenta",
            id=decision_id,
        )
        replay = await _decide(
            analyst,
            suggestion_id,
            1,
            "reject",
            reason="Ese cobro es de otra cuenta",
            id=decision_id,
        )
        twice = await _decide(analyst, suggestion_id, 1, "accept")
        missing = await _decide(analyst, suggestion_id, 2, "accept")

    assert (no_reason.status_code, no_reason.json()["detail"]) == (422, "reason_required")
    assert (rejected.status_code, replay.status_code) == (201, 200)
    assert replay.json() == rejected.json()
    assert (rejected.json()["reason"], rejected.json()["match_id"]) == (
        "Ese cobro es de otra cuenta",
        None,
    )
    assert (twice.status_code, twice.json()["detail"]) == (409, "already_decided")
    assert (missing.status_code, missing.json()["detail"]) == (404, "not_found")


async def test_an_invalid_output_cannot_be_decided(
    database: DatabaseUrls, owner_engine: AsyncEngine, worker_engine: AsyncEngine, books: Setup
) -> None:
    llm = LlmClients(real=FakeLlmClient(lambda _user: "no json"))
    async with ai_app(database, llm) as app, signed_in(app, books.member.email) as analyst:
        suggestion_id = await _suggested(analyst, owner_engine, worker_engine, books, llm)
        response = await _decide(analyst, suggestion_id, 0, "accept")

    assert (response.status_code, response.json()["detail"]) == (409, "invalid_suggestion")


async def test_two_analysts_accepting_at_once_create_one_match(
    database: DatabaseUrls, owner_engine: AsyncEngine, worker_engine: AsyncEngine, books: Setup
) -> None:
    other = await add_member(owner_engine, NOW, books.organization_id, ["analyst"])
    llm = LlmClients(real=FakeLlmClient(TWO_WAYS))
    async with (
        ai_app(database, llm) as app,
        signed_in(app, books.member.email) as first,
        signed_in(app, other.email) as second,
    ):
        suggestion_id = await _suggested(first, owner_engine, worker_engine, books, llm)
        responses = await asyncio.gather(
            _decide(first, suggestion_id, 0, "accept"),
            _decide(second, suggestion_id, 1, "accept"),
        )

    assert sorted(r.status_code for r in responses) == [201, 409]
    async with owner_engine.connect() as connection:
        matches = await connection.scalar(
            text("SELECT count(*) FROM matches WHERE organization_id = :org AND source = 'ai'"),
            {"org": books.organization_id},
        )
    assert matches == 1


async def test_only_analysts_decide_and_suggestions_stay_inside_their_organization(
    database: DatabaseUrls, owner_engine: AsyncEngine, worker_engine: AsyncEngine, books: Setup
) -> None:
    reviewer = await add_member(owner_engine, NOW, books.organization_id, ["reviewer"])
    stranger = await statement_setup(owner_engine, ["analyst"])
    llm = LlmClients(real=FakeLlmClient(TWO_WAYS))
    async with ai_app(database, llm) as app:
        async with signed_in(app, books.member.email) as analyst:
            suggestion_id = await _suggested(analyst, owner_engine, worker_engine, books, llm)
        async with signed_in(app, reviewer.email) as client:
            not_analyst = await _decide(client, suggestion_id, 0, "accept")
        async with signed_in(app, stranger.member.email) as client:
            foreign = await _decide(client, suggestion_id, 0, "accept")

    assert (not_analyst.status_code, not_analyst.json()["detail"]) == (403, "role_required")
    assert (foreign.status_code, foreign.json()["detail"]) == (404, "not_found")


async def test_usage_counts_todays_requests_against_the_daily_limit(
    database: DatabaseUrls, owner_engine: AsyncEngine, books: Setup
) -> None:
    credit = await credit_of(owner_engine, books, 50_000)
    llm = LlmClients(real=FakeLlmClient())
    async with ai_app(database, llm) as app, signed_in(app, books.member.email) as analyst:
        before = (await analyst.get("/api/app/ai/usage")).json()
        await ask_ai(analyst, credit)
        await ask_ai(analyst, credit)
        after = (await analyst.get("/api/app/ai/usage")).json()
    without_key = LlmClients(real=None)
    async with ai_app(database, without_key) as app, signed_in(app, books.member.email) as analyst:
        unavailable = (await analyst.get("/api/app/ai/usage")).json()

    assert before == {"available": True, "used_today": 0, "daily_limit": 50}
    assert after["used_today"] == 2
    assert unavailable["available"] is False
