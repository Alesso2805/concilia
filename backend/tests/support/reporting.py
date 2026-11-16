from typing import Any

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.support.api import Member, add_member, signed_in, xsrf_header
from tests.support.clock import FixedClock
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


async def post_new(client: httpx.AsyncClient, path: str, body: dict[str, Any]) -> httpx.Response:
    return await client.post(path, json={"id": client_id(), **body}, headers=xsrf_header(client))


async def reconciled_books(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine
) -> tuple[Setup, Member]:
    """January approved by the engine's proposal; February confirmed by hand with a 5.00
    commission."""
    clock = FixedClock(NOW)
    setup = await statement_setup(owner_engine)
    reviewer = await add_member(owner_engine, NOW, setup.organization_id, ["reviewer"])
    profile_id = await receivables_profile(owner_engine, setup)
    account = str(setup.account_id)
    async with signed_in(app, setup.member.email) as analyst:
        for content, profile in ((STATEMENT, None), (RECEIVABLES, profile_id)):
            file_id = (await upload(analyst, setup, content, profile_id=profile)).json()["file"][
                "id"
            ]
            await work(worker_engine, clock)
            await analyst.post(f"/api/app/imports/{file_id}/confirm", headers=xsrf_header(analyst))
            await work(worker_engine, clock)
        await post_new(
            analyst, "/api/app/engine-runs", {"bank_account_id": account, "period": "2027-01-01"}
        )
        await work(worker_engine, clock)
        [match] = (
            await analyst.get(
                "/api/app/matches", params={"bank_account_id": account, "period": "2027-01-01"}
            )
        ).json()["matches"]
        await post_new(analyst, f"/api/app/matches/{match['id']}/decisions", {"action": "confirm"})
        [credit] = (
            await analyst.get(
                "/api/app/inbox/credits",
                params={"bank_account_id": account, "period": "2027-02-01"},
            )
        ).json()["credits"]
        [receivable] = (
            await analyst.get("/api/app/inbox/receivables", params={"q": "F001-124"})
        ).json()["receivables"]
        manual = await post_new(
            analyst,
            "/api/app/matches",
            {
                "bank_account_id": account,
                "credit_ids": [credit["id"]],
                "applications": [{"receivable_id": receivable["id"], "applied_cents": 49_500}],
                "difference_reason": "commission",
            },
        )
        assert manual.status_code == 201
    async with signed_in(app, reviewer.email) as client:
        await post_new(client, f"/api/app/matches/{match['id']}/decisions", {"action": "approve"})
    return setup, reviewer
