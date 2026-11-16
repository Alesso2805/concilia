from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.support.api import ORIGIN, build_app, create_member, signed_in, xsrf_header
from tests.support.clock import FixedClock
from tests.support.database import DatabaseUrls
from tests.support.imports import NOW, client_id, work
from tests.support.statistics import all_grew, manual_analyze_counts

pytestmark = pytest.mark.anyio

FIRST_MONTH_PROPOSALS = 103
FIRST_MONTH_FREE = 12
SECOND_MONTH_CREDITS = 118


@asynccontextmanager
async def _app(database: DatabaseUrls, **overrides: Any) -> AsyncIterator[FastAPI]:
    app = build_app(database.for_role("concilia_app"), FixedClock(NOW), **overrides)
    yield app
    await app.state.engine.dispose()


@asynccontextmanager
async def _visitor(app: FastAPI, ip: str = "203.0.113.7") -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, client=(ip, 50_000))
    async with httpx.AsyncClient(
        transport=transport, base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as client:
        yield client


async def _counts(client: httpx.AsyncClient, account: str, period: str) -> dict[str, Any]:
    response = await client.get(
        "/api/app/inbox/counts", params={"bank_account_id": account, "period": period}
    )
    counts: dict[str, Any] = response.json()
    return counts


async def test_a_visitor_enters_a_demo_with_two_imported_months_as_its_analyst(
    database: DatabaseUrls, owner_engine: AsyncEngine
) -> None:
    async with _app(database) as app, _visitor(app) as client:
        created = await client.post("/api/public/demo")
        session = (await client.get("/api/app/session")).json()
        [account] = (await client.get("/api/app/bank-accounts")).json()
        files = (await client.get("/api/app/imports")).json()["files"]
        october = await _counts(client, account["id"], "2026-10-01")
        november = await _counts(client, account["id"], "2026-11-01")
        periods = (
            await client.get("/api/app/inbox/periods", params={"bank_account_id": account["id"]})
        ).json()

    organization_id = created.json()["organization_id"]
    assert created.status_code == 201
    assert (session["organization_id"], session["roles"]) == (organization_id, ["analyst"])
    assert session["organizations"][0]["is_demo"] is True
    assert sorted((file["kind"], file["status"]) for file in files) == [
        ("bank_statement", "confirmed"),
        ("bank_statement", "confirmed"),
        ("receivables", "confirmed"),
        ("receivables", "confirmed"),
    ]
    assert october == {
        "free": FIRST_MONTH_FREE,
        "proposed": 0,
        "confirmed": 0,
        "approved": FIRST_MONTH_PROPOSALS,
    }
    assert (november["proposed"], november["free"]) == (0, SECOND_MONTH_CREDITS)
    assert [(period["period"], period["closed"]) for period in periods] == [
        ("2026-11-01", False),
        ("2026-10-01", True),
    ]
    async with owner_engine.connect() as connection:
        organization = (
            await connection.execute(
                text("SELECT is_demo, demo_expires_at FROM organizations WHERE id = :id"),
                {"id": organization_id},
            )
        ).one()
        users = (
            await connection.execute(
                text(
                    """SELECT u.email, u.password_hash, u.is_demo, r.role
                       FROM users u JOIN member_roles r ON r.user_id = u.id
                       WHERE r.organization_id = :id ORDER BY r.role"""
                ),
                {"id": organization_id},
            )
        ).all()
        run = (
            await connection.execute(
                text(
                    """SELECT job_id, period, proposals_count FROM engine_runs
                       WHERE organization_id = :id"""
                ),
                {"id": organization_id},
            )
        ).one()
        audit = (
            await connection.execute(
                text(
                    """SELECT action, metadata FROM audit_events
                       WHERE organization_id = :id AND entity = 'organization'"""
                ),
                {"id": organization_id},
            )
        ).one()
        decisions: dict[str, int] = dict(
            (
                await connection.execute(
                    text(
                        """SELECT action, count(*) FROM audit_events
                           WHERE organization_id = :id AND entity IN ('match', 'period_event')
                           GROUP BY action"""
                    ),
                    {"id": organization_id},
                )
            ).all()
        )
    assert organization.is_demo is True
    assert organization.demo_expires_at == datetime(9999, 12, 31, tzinfo=UTC)
    assert [user.role for user in users] == ["admin", "analyst", "reviewer"]
    assert all(
        user.email.startswith("demo+")
        and user.email.endswith("@concilia.invalid")
        and user.password_hash is None
        and user.is_demo
        for user in users
    )
    assert (run.job_id, run.period.isoformat(), run.proposals_count) == (
        None,
        "2026-10-01",
        FIRST_MONTH_PROPOSALS,
    )
    assert (audit.action, audit.metadata) == ("organization.created", {"source": "demo"})
    assert decisions == {
        "match.confirmed": FIRST_MONTH_PROPOSALS,
        "match.approved": FIRST_MONTH_PROPOSALS,
        "period.closed": 1,
    }


async def test_creating_a_demo_refreshes_the_planner_statistics(
    database: DatabaseUrls, owner_engine: AsyncEngine
) -> None:
    before = await manual_analyze_counts(owner_engine)
    async with _app(database) as app, _visitor(app, ip="203.0.113.70") as client:
        created = await client.post("/api/public/demo")

    assert created.status_code == 201
    assert all_grew(before, await manual_analyze_counts(owner_engine))


async def test_a_published_demo_expires_after_its_ttl(
    database: DatabaseUrls, owner_engine: AsyncEngine
) -> None:
    async with _app(database, demo_ttl_hours=4) as app, _visitor(app) as client:
        organization_id = (await client.post("/api/public/demo")).json()["organization_id"]

    async with owner_engine.connect() as connection:
        expires = await connection.scalar(
            text("SELECT demo_expires_at FROM organizations WHERE id = :id"),
            {"id": organization_id},
        )
    assert expires == NOW + timedelta(hours=4)


async def test_each_visitor_gets_an_isolated_demo(database: DatabaseUrls) -> None:
    async with _app(database) as app:
        async with _visitor(app) as first:
            one = (await first.post("/api/public/demo")).json()["organization_id"]
            first_files = {
                file["id"] for file in (await first.get("/api/app/imports")).json()["files"]
            }
        async with _visitor(app) as second:
            other = (await second.post("/api/public/demo")).json()["organization_id"]
            second_files = {
                file["id"] for file in (await second.get("/api/app/imports")).json()["files"]
            }

    assert one != other
    assert len(first_files) == len(second_files) == 4
    assert not first_files & second_files


async def test_demos_are_limited_per_ip_and_per_day(database: DatabaseUrls) -> None:
    async with _app(database, demo_max_per_ip_per_day=1, demo_max_per_day=2) as app:
        async with _visitor(app, "198.51.100.1") as first:
            allowed = await first.post("/api/public/demo")
            same_ip = await first.post("/api/public/demo")
        async with _visitor(app, "198.51.100.2") as second:
            other_ip = await second.post("/api/public/demo")
        async with _visitor(app, "198.51.100.3") as third:
            over_total = await third.post("/api/public/demo")

    assert (allowed.status_code, other_ip.status_code) == (201, 201)
    assert (same_ip.status_code, same_ip.json()["detail"]) == (429, "demo_limit")
    assert (over_total.status_code, over_total.json()["detail"]) == (429, "demo_limit")


async def test_creating_a_demo_requires_the_site_origin(database: DatabaseUrls) -> None:
    async with _app(database) as app:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as client:
            response = await client.post(
                "/api/public/demo", headers={"Origin": "https://attacker.example"}
            )

    assert response.status_code == 403


async def test_a_visitor_switches_role_into_a_new_session(
    database: DatabaseUrls, owner_engine: AsyncEngine
) -> None:
    async with _app(database) as app, _visitor(app) as client:
        organization_id = (await client.post("/api/public/demo")).json()["organization_id"]
        analyst = (await client.get("/api/app/session")).json()
        old_cookie = client.cookies.get("__Host-concilia_session")
        switched = await client.post(
            "/api/app/demo/switch-role", json={"role": "reviewer"}, headers=xsrf_header(client)
        )
        reviewer = (await client.get("/api/app/session")).json()
        async with _visitor(app) as stale:
            stale.cookies.set("__Host-concilia_session", old_cookie or "")
            revoked = await stale.get("/api/app/session")

    assert (switched.status_code, switched.json()) == (200, {"role": "reviewer"})
    assert (reviewer["organization_id"], reviewer["roles"]) == (organization_id, ["reviewer"])
    assert reviewer["user_id"] != analyst["user_id"]
    assert revoked.status_code == 401
    async with owner_engine.connect() as connection:
        event = (
            await connection.execute(
                text(
                    """SELECT actor_user_id, entity_id, metadata FROM audit_events
                       WHERE organization_id = :id AND action = 'demo.role_switched'"""
                ),
                {"id": organization_id},
            )
        ).one()
    assert (str(event.actor_user_id), str(event.entity_id), event.metadata) == (
        analyst["user_id"],
        reviewer["user_id"],
        {"roles": ["reviewer"]},
    )


async def test_switching_role_needs_a_live_demo(
    database: DatabaseUrls, owner_engine: AsyncEngine
) -> None:
    member = await create_member(owner_engine, NOW, organizations={"Real": ["analyst"]})
    async with _app(database) as app:
        async with signed_in(app, member.email) as client:
            real = await client.post(
                "/api/app/demo/switch-role", json={"role": "admin"}, headers=xsrf_header(client)
            )
        async with _visitor(app) as client:
            organization_id = (await client.post("/api/public/demo")).json()["organization_id"]
            async with owner_engine.begin() as connection:
                await connection.execute(
                    text("UPDATE organizations SET demo_expires_at = :past WHERE id = :id"),
                    {"past": NOW - timedelta(minutes=1), "id": organization_id},
                )
            expired = await client.post(
                "/api/app/demo/switch-role", json={"role": "admin"}, headers=xsrf_header(client)
            )

    assert (real.status_code, real.json()["detail"]) == (403, "not_a_demo")
    assert (expired.status_code, expired.json()["detail"]) == (403, "not_a_demo")


async def test_the_third_month_downloads_and_imports_with_its_overlap(
    database: DatabaseUrls, owner_engine: AsyncEngine, worker_engine: AsyncEngine
) -> None:
    member = await create_member(owner_engine, NOW, organizations={"Real": ["analyst"]})
    async with _app(database) as app:
        async with _visitor(app) as client:
            await client.post("/api/public/demo")
            statement = await client.get("/api/app/demo/files/statement")
            receivables = await client.get("/api/app/demo/files/receivables")
            profiles = (await client.get("/api/app/import-profiles")).json()
            profile = next(p for p in profiles if p["kind"] == "bank_statement")
            uploaded = await client.post(
                "/api/app/imports",
                data={"id": client_id(), "import_profile_id": profile["id"]},
                files={"file": ("extracto-2026-12.csv", statement.content, "text/csv")},
                headers=xsrf_header(client),
            )
            await work(worker_engine, FixedClock(NOW))
            counts = (await client.get(f"/api/app/imports/{uploaded.json()['file']['id']}")).json()
        async with signed_in(app, member.email) as client:
            refused = await client.get("/api/app/demo/files/statement")

    lines = statement.text.splitlines()
    assert statement.headers["content-type"].startswith("text/csv")
    assert 'filename="extracto-2026-12.csv"' in statement.headers["content-disposition"]
    assert lines[0] == "Fecha;Descripción;Operación;Monto"
    assert [line[3:10] for line in lines[1:4]] == ["11/2026"] * 3
    assert 'filename="cobros-2026-12.csv"' in receivables.headers["content-disposition"]
    assert receivables.text.startswith("Cliente,RUC,Documento,Emisión,Vencimiento,Monto\n")
    assert (counts["counts"]["duplicate"], counts["counts"]["ok"]) == (3, len(lines) - 4)
    assert (refused.status_code, refused.json()["detail"]) == (403, "not_a_demo")
