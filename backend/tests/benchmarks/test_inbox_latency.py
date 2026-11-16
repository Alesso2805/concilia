import time
from collections.abc import AsyncIterator, Awaitable, Callable
from statistics import quantiles

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.support.api import add_member, build_app, signed_in
from tests.support.clock import FixedClock
from tests.support.database import DatabaseUrls
from tests.support.imports import NOW, Setup, statement_setup

pytestmark = pytest.mark.anyio

MOVEMENTS = 10_000
MATCHED = 6_000
REQUESTS_PER_ENDPOINT = 20
P95_LIMIT_SECONDS = 0.5

SEED = [
    "ALTER TABLE matches DISABLE TRIGGER USER",
    "ALTER TABLE match_items DISABLE TRIGGER USER",
    "ALTER TABLE match_decisions DISABLE TRIGGER USER",
    """INSERT INTO import_files (id, organization_id, kind, bank_account_id, import_profile_id,
                                 profile_snapshot, filename, sha256, size_bytes, content, status,
                                 created_by, created_at)
       VALUES (md5('file')::uuid, :org, 'bank_statement', :account, :profile, '{}', 'big.csv',
               repeat('c', 64), 3, 'abc', 'confirmed', :analyst, :now)""",
    """INSERT INTO bank_movements (id, organization_id, bank_account_id, import_file_id,
                                   booked_on, amount_cents, description, description_norm,
                                   fingerprint, doc_refs, created_at)
       SELECT md5('m' || n)::uuid, :org, :account, md5('file')::uuid,
              DATE '2027-01-01' + (n % 31), 1000 + n, 'PAGO ' || n, 'PAGO ' || n,
              md5('m' || n) || md5('f' || n), '{}', :now
       FROM generate_series(1, :movements) n""",
    """INSERT INTO receivables (id, organization_id, import_file_id, customer_name,
                                customer_name_norm, doc_number, doc_number_norm, issued_on,
                                due_on, amount_cents, created_at, updated_at)
       SELECT md5('r' || n)::uuid, :org, md5('file')::uuid, 'Cliente ' || (n % 300),
              'CLIENTE ' || (n % 300), 'F001-' || n, 'F001-' || n, DATE '2026-12-15',
              DATE '2027-01-15', 1000 + n, :now, :now
       FROM generate_series(1, :movements) n""",
    """INSERT INTO matches (id, organization_id, bank_account_id, source, created_by, created_at)
       SELECT md5('x' || n)::uuid, :org, :account, 'manual', :analyst, :now
       FROM generate_series(1, :matched) n""",
    """INSERT INTO match_items (id, organization_id, match_id, bank_movement_id)
       SELECT md5('i' || n)::uuid, :org, md5('x' || n)::uuid, md5('m' || n)::uuid
       FROM generate_series(1, :matched) n""",
    """INSERT INTO match_items (id, organization_id, match_id, receivable_id, applied_cents)
       SELECT md5('j' || n)::uuid, :org, md5('x' || n)::uuid, md5('r' || n)::uuid, 1000 + n
       FROM generate_series(1, :matched) n""",
    """INSERT INTO match_decisions (id, organization_id, match_id, action, decided_by, decided_at)
       SELECT md5('c' || n)::uuid, :org, md5('x' || n)::uuid, 'confirm', :analyst, :now
       FROM generate_series(:matched / 3 + 1, :matched) n""",
    """INSERT INTO match_decisions (id, organization_id, match_id, action, decided_by, decided_at)
       SELECT md5('a' || n)::uuid, :org, md5('x' || n)::uuid, 'approve', :reviewer, :now
       FROM generate_series(2 * :matched / 3 + 1, :matched) n""",
    "ALTER TABLE matches ENABLE TRIGGER USER",
    "ALTER TABLE match_items ENABLE TRIGGER USER",
    "ALTER TABLE match_decisions ENABLE TRIGGER USER",
]


@pytest.fixture
async def app(database: DatabaseUrls) -> AsyncIterator[FastAPI]:
    app = build_app(database.for_role("concilia_app"), FixedClock(NOW))
    yield app
    await app.state.engine.dispose()


@pytest.fixture
async def books(owner_engine: AsyncEngine) -> Setup:
    setup = await statement_setup(owner_engine)
    reviewer = await add_member(owner_engine, NOW, setup.organization_id, ["reviewer"])
    params = {
        "org": setup.organization_id,
        "account": setup.account_id,
        "profile": setup.profile_id,
        "analyst": setup.member.user_id,
        "reviewer": reviewer.user_id,
        "now": NOW,
        "movements": MOVEMENTS,
        "matched": MATCHED,
    }
    async with owner_engine.begin() as connection:
        for statement in SEED:
            await connection.execute(text(statement), params)
    async with owner_engine.connect() as connection:
        await connection.execution_options(isolation_level="AUTOCOMMIT")
        await connection.execute(text("ANALYZE"))
    return setup


async def _p95(request: Callable[[], Awaitable[httpx.Response]]) -> float:
    durations = []
    for _ in range(REQUESTS_PER_ENDPOINT):
        started = time.perf_counter()
        response = await request()
        durations.append(time.perf_counter() - started)
        assert response.status_code == 200, response.text
    return quantiles(durations, n=20)[-1]


async def test_the_inbox_answers_within_500_ms_at_p95_with_10_000_movements(
    app: FastAPI, books: Setup
) -> None:
    month = {"bank_account_id": str(books.account_id), "period": "2027-01-01"}
    async with signed_in(app, books.member.email) as client:
        first = (await client.get("/api/app/matches", params=month)).json()
        assert len(first["matches"]) == 25
        endpoints: dict[str, Callable[[], Awaitable[httpx.Response]]] = {
            "periods": lambda: client.get(
                "/api/app/inbox/periods", params={"bank_account_id": str(books.account_id)}
            ),
            "counts": lambda: client.get("/api/app/inbox/counts", params=month),
            "free credits": lambda: client.get("/api/app/inbox/credits", params=month),
            "proposed": lambda: client.get("/api/app/matches", params=month),
            "approved, next page": lambda: client.get(
                "/api/app/matches",
                params={**month, "status": "approved", "after": first["next_cursor"]},
            ),
            "confirmed by amount": lambda: client.get(
                "/api/app/matches",
                params={**month, "status": "confirmed", "min_amount_cents": 5_000},
            ),
            "detail": lambda: client.get(f"/api/app/matches/{first['matches'][0]['id']}"),
        }
        p95 = {name: await _p95(request) for name, request in endpoints.items()}
        counts = (await client.get("/api/app/inbox/counts", params=month)).json()

    assert counts == {"free": 4_000, "proposed": 2_000, "confirmed": 2_000, "approved": 2_000}
    slow = {
        name: round(seconds, 3) for name, seconds in p95.items() if seconds >= P95_LIMIT_SECONDS
    }
    assert slow == {}
