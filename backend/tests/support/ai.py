import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from concilia.ai.infrastructure.clients import LlmClients
from concilia.shared.infrastructure.jobs import Runner
from concilia.worker import handlers
from tests.support.api import build_app, signed_in, xsrf_header
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

CLOCK = FixedClock(NOW)


def answer(*suggestions: dict[str, Any], no_match: str | None = None) -> Callable[[str], str]:
    return lambda _user: json.dumps({"suggestions": list(suggestions), "no_match_reason": no_match})


def model_suggestion(
    candidates: list[str], applied: list[tuple[str, int]] | None
) -> dict[str, Any]:
    return {
        "candidates": candidates,
        "applied": [{"alias": a, "cents": c} for a, c in applied] if applied is not None else None,
        "confidence": "high",
        "explanation": "El monto coincide con el saldo de F001-124.",
        "difference_reason": None,
    }


@asynccontextmanager
async def ai_app(
    database: DatabaseUrls, llm: LlmClients | None, **settings: Any
) -> AsyncIterator[FastAPI]:
    app = build_app(
        database.for_role("concilia_app"), CLOCK, llm=llm, **{"ai_enabled": True, **settings}
    )
    yield app
    await app.state.engine.dispose()


async def run_ai_jobs(worker_engine: AsyncEngine, llm: LlmClients) -> None:
    runner = Runner(worker_engine, CLOCK, handlers(worker_engine, CLOCK, llm))
    while await runner.run_once():
        pass


async def imported_books(
    database: DatabaseUrls, owner_engine: AsyncEngine, worker_engine: AsyncEngine
) -> Setup:
    """January and February imported; no engine run, so both credits are free."""
    setup = await statement_setup(owner_engine, ["analyst"])
    profile_id = await receivables_profile(owner_engine, setup)
    app = build_app(database.for_role("concilia_app"), CLOCK)
    try:
        async with signed_in(app, setup.member.email) as analyst:
            for content, profile in ((STATEMENT, None), (RECEIVABLES, profile_id)):
                response = await upload(analyst, setup, content, profile_id=profile)
                await work(worker_engine, CLOCK)
                file_id = response.json()["file"]["id"]
                await analyst.post(
                    f"/api/app/imports/{file_id}/confirm", headers=xsrf_header(analyst)
                )
                await work(worker_engine, CLOCK)
    finally:
        await app.state.engine.dispose()
    return setup


async def credit_of(owner_engine: AsyncEngine, setup: Setup, amount: int) -> str:
    async with owner_engine.connect() as connection:
        found = await connection.scalar(
            text(
                """SELECT id FROM bank_movements
                   WHERE bank_account_id = :account AND amount_cents = :amount"""
            ),
            {"account": setup.account_id, "amount": amount},
        )
    return str(found)


async def ask_ai(
    client: httpx.AsyncClient, credit_id: str, suggestion_id: str | None = None
) -> httpx.Response:
    return await client.post(
        "/api/app/ai/suggestions",
        json={"id": suggestion_id or client_id(), "bank_movement_id": credit_id},
        headers=xsrf_header(client),
    )
