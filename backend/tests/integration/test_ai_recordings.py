from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from concilia.ai.application.response import parse_output
from concilia.ai.domain.suggestions import choose_candidates
from concilia.ai.infrastructure.clients import LlmClients
from concilia.ai.infrastructure.recordings import RecordedReplayer, Recordings, to_documents
from concilia.ai.infrastructure.sql import SqlSuggestionStore
from concilia.audit.infrastructure.sql import SqlAuditRecorder
from concilia.shared.infrastructure.db import organization_transaction
from concilia.shared.infrastructure.jobs import Runner
from concilia.worker import handlers
from tests.support.ai import CLOCK, answer, ask_ai, model_suggestion, run_ai_jobs
from tests.support.api import ORIGIN, build_app
from tests.support.database import DatabaseUrls

pytestmark = pytest.mark.anyio

NOVEMBER = "2026-11-01"


async def _demo(app: FastAPI, ip: str) -> tuple[httpx.AsyncClient, UUID]:
    transport = httpx.ASGITransport(app=app, client=(ip, 50_000))
    client = httpx.AsyncClient(transport=transport, base_url=ORIGIN, headers={"Origin": ORIGIN})
    created = await client.post("/api/public/demo")
    assert created.status_code == 201
    return client, UUID(created.json()["organization_id"])


async def _first_credit(client: httpx.AsyncClient) -> dict[str, Any]:
    [account] = (await client.get("/api/app/bank-accounts")).json()
    credits = (
        await client.get(
            "/api/app/inbox/credits",
            params={"bank_account_id": account["id"], "period": NOVEMBER, "limit": 1},
        )
    ).json()["credits"]
    first: dict[str, Any] = credits[0]
    return first


async def test_the_same_recording_replays_in_two_different_demos(
    database: DatabaseUrls, owner_engine: AsyncEngine, worker_engine: AsyncEngine
) -> None:
    no_provider = LlmClients(real=None)
    await run_ai_jobs(worker_engine, no_provider)
    llm = no_provider
    recorder = build_app(database.for_role("concilia_app"), CLOCK, ai_enabled=True, llm=llm)
    first, first_org = await _demo(recorder, "203.0.113.101")
    credit = await _first_credit(first)
    async with organization_transaction(owner_engine, first_org) as connection:
        store = SqlSuggestionStore(connection, SqlAuditRecorder(connection))
        facts = await store.free_credit(UUID(credit["id"]))
        assert facts is not None
        candidates = choose_candidates(facts, await store.open_receivables())
        key = await store.credit_key(facts.id)
    output = parse_output(answer(model_suggestion(["C1"], None))(""))
    assert output is not None
    recordings = Recordings(1, 1, "gpt-6-luna", {key: to_documents(output, candidates)})
    replayer = RecordedReplayer(recordings)
    await first.aclose()
    await recorder.state.engine.dispose()

    app = build_app(
        database.for_role("concilia_app"), CLOCK, ai_enabled=True, llm=llm, replayer=replayer
    )
    runner = Runner(worker_engine, CLOCK, handlers(worker_engine, CLOCK, llm, replayer))
    views = []
    try:
        for ip in ("203.0.113.102", "203.0.113.103"):
            client, _ = await _demo(app, ip)
            try:
                request = await ask_ai(client, (await _first_credit(client))["id"])
                while await runner.run_once():
                    pass
                views.append(
                    (await client.get(f"/api/app/ai/suggestions/{request.json()['id']}")).json()
                )
            finally:
                await client.aclose()
    finally:
        await app.state.engine.dispose()

    recorded_document = candidates[0].receivable.doc_number
    [first_view, second_view] = views
    for view in views:
        assert (view["status"], view["valid"]) == ("done", True)
        assert [r["doc_number"] for r in view["suggestions"][0]["receivables"]] == [
            recorded_document
        ]
    first_ids = [r["receivable_id"] for r in first_view["suggestions"][0]["receivables"]]
    second_ids = [r["receivable_id"] for r in second_view["suggestions"][0]["receivables"]]
    assert first_ids != second_ids
