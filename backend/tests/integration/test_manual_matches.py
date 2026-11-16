import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid7

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.support.api import Member, add_member, build_app, signed_in, xsrf_header
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

pytestmark = pytest.mark.anyio


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
async def app(database: DatabaseUrls, clock: FixedClock) -> AsyncIterator[FastAPI]:
    app = build_app(database.for_role("concilia_app"), clock)
    yield app
    await app.state.engine.dispose()


@dataclass(frozen=True)
class Books:
    setup: Setup
    reviewer: Member
    january: UUID
    february: UUID
    debit: UUID
    invoice: UUID
    small_invoice: UUID


async def _import(
    client: httpx.AsyncClient,
    setup: Setup,
    worker_engine: AsyncEngine,
    clock: FixedClock,
    content: bytes,
    profile_id: UUID | None = None,
) -> None:
    response = await upload(client, setup, content, profile_id=profile_id)
    await work(worker_engine, clock)
    file_id = response.json()["file"]["id"]
    await client.post(f"/api/app/imports/{file_id}/confirm", headers=xsrf_header(client))
    await work(worker_engine, clock)


@pytest.fixture
async def books(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> Books:
    setup = await statement_setup(owner_engine)
    reviewer = await add_member(owner_engine, NOW, setup.organization_id, ["reviewer"])
    profile_id = await receivables_profile(owner_engine, setup)
    async with signed_in(app, setup.member.email) as client:
        await _import(client, setup, worker_engine, clock, STATEMENT)
        await _import(client, setup, worker_engine, clock, RECEIVABLES, profile_id)
    async with owner_engine.connect() as connection:
        movements: dict[int, UUID] = dict(
            (
                await connection.execute(
                    text(
                        """SELECT amount_cents, id FROM bank_movements
                           WHERE organization_id = :org"""
                    ),
                    {"org": setup.organization_id},
                )
            ).all()
        )
        invoices: dict[str, UUID] = dict(
            (
                await connection.execute(
                    text(
                        """SELECT doc_number_norm, id FROM receivables
                           WHERE organization_id = :org"""
                    ),
                    {"org": setup.organization_id},
                )
            ).all()
        )
    return Books(
        setup,
        reviewer,
        movements[118_000],
        movements[50_000],
        movements[-1_250],
        invoices["F001-123"],
        invoices["F001-124"],
    )


async def _create(
    client: httpx.AsyncClient,
    books: Books,
    credits: list[UUID],
    applications: list[tuple[UUID, int]],
    **fields: Any,
) -> httpx.Response:
    return await client.post(
        "/api/app/matches",
        json={
            "id": fields.pop("id", None) or client_id(),
            "bank_account_id": str(fields.pop("account", books.setup.account_id)),
            "credit_ids": [str(credit) for credit in credits],
            "applications": [
                {"receivable_id": str(receivable), "applied_cents": applied}
                for receivable, applied in applications
            ],
            **fields,
        },
        headers=xsrf_header(client),
    )


async def _available(owner_engine: AsyncEngine, receivable: UUID) -> int:
    async with owner_engine.connect() as connection:
        available: int = await connection.scalar(
            text("SELECT available_cents FROM receivable_balances WHERE receivable_id = :id"),
            {"id": receivable},
        )
        return available


async def test_an_analyst_reconciles_by_hand_and_confirms_at_once(
    app: FastAPI, owner_engine: AsyncEngine, books: Books
) -> None:
    match_id = client_id()
    async with signed_in(app, books.setup.member.email) as analyst:
        created = await _create(
            analyst, books, [books.january], [(books.invoice, 118_000)], id=match_id
        )
        replay = await _create(
            analyst, books, [books.january], [(books.invoice, 118_000)], id=match_id
        )
        reused = await _create(analyst, books, [books.february], [(books.invoice, 1)], id=match_id)
        detail = (await analyst.get(f"/api/app/matches/{match_id}")).json()
    async with signed_in(app, books.reviewer.email) as reviewer:
        approved = await reviewer.post(
            f"/api/app/matches/{match_id}/decisions",
            json={"id": client_id(), "action": "approve"},
            headers=xsrf_header(reviewer),
        )

    assert (created.status_code, created.json()) == (201, {"id": match_id, "status": "confirmed"})
    assert replay.status_code == 200
    assert (reused.status_code, reused.json()["detail"]) == (409, "id_conflict")
    assert (detail["source"], detail["status"], detail["rule"]) == ("manual", "confirmed", None)
    assert [d["action"] for d in detail["decisions"]] == ["confirm"]
    assert approved.status_code == 201
    async with owner_engine.connect() as connection:
        events = (
            await connection.execute(
                text(
                    """SELECT action, metadata FROM audit_events
                       WHERE entity_id = :id ORDER BY seq"""
                ),
                {"id": match_id},
            )
        ).all()
    assert [(e.action, e.metadata) for e in events] == [
        ("match.created", {"source": "manual"}),
        ("match.confirmed", {}),
        ("match.approved", {}),
    ]


async def test_a_partial_payment_leaves_the_rest_of_the_receivable_open(
    app: FastAPI, owner_engine: AsyncEngine, books: Books
) -> None:
    async with signed_in(app, books.setup.member.email) as analyst:
        created = await _create(analyst, books, [books.february], [(books.invoice, 50_000)])

    assert created.status_code == 201
    assert await _available(owner_engine, books.invoice) == 68_000


async def test_a_difference_needs_a_fitting_reason(app: FastAPI, books: Books) -> None:
    async with signed_in(app, books.setup.member.email) as analyst:
        missing = await _create(analyst, books, [books.january], [(books.small_invoice, 50_000)])
        created = await _create(
            analyst,
            books,
            [books.january],
            [(books.small_invoice, 50_000)],
            difference_reason="overpayment",
        )

    assert (missing.status_code, missing.json()["detail"]) == (422, "difference_reason")
    assert created.status_code == 201


async def test_items_must_be_free_and_have_balance(
    app: FastAPI, owner_engine: AsyncEngine, books: Books
) -> None:
    async with signed_in(app, books.setup.member.email) as analyst:
        too_much = await _create(analyst, books, [books.january], [(books.invoice, 118_001)])
        debit = await _create(analyst, books, [books.debit], [(books.invoice, 1_250)])
        await _create(analyst, books, [books.january], [(books.invoice, 118_000)])
        taken = await _create(analyst, books, [books.january], [(books.small_invoice, 50_000)])
        unknown = await _create(analyst, books, [books.february], [(uuid7(), 50_000)])
        repeated = await _create(
            analyst, books, [books.february, books.february], [(books.small_invoice, 50_000)]
        )
    async with signed_in(app, books.reviewer.email) as reviewer:
        not_analyst = await _create(reviewer, books, [books.february], [(books.small_invoice, 1)])

    assert (too_much.status_code, too_much.json()["detail"]) == (409, "insufficient_balance")
    assert (debit.status_code, debit.json()["detail"]) == (409, "credit_not_free")
    assert (taken.status_code, taken.json()["detail"]) == (409, "credit_not_free")
    assert unknown.status_code == 404
    assert (repeated.status_code, repeated.json()["detail"]) == (422, "invalid_match")
    assert (not_analyst.status_code, not_analyst.json()["detail"]) == (403, "role_required")


async def test_nothing_is_reconciled_in_a_closed_month(
    app: FastAPI, owner_engine: AsyncEngine, books: Books
) -> None:
    async with owner_engine.begin() as connection:
        await connection.execute(
            text(
                """INSERT INTO period_events (id, organization_id, bank_account_id, period,
                                              action, decided_by, decided_at)
                   VALUES (:id, :org, :account, '2027-01-01', 'close', :user, :now)"""
            ),
            {
                "id": uuid7(),
                "org": books.setup.organization_id,
                "account": books.setup.account_id,
                "user": books.reviewer.user_id,
                "now": NOW,
            },
        )
    async with signed_in(app, books.setup.member.email) as analyst:
        refused = await _create(analyst, books, [books.january], [(books.invoice, 118_000)])

    assert (refused.status_code, refused.json()["detail"]) == (409, "closed_period")
    assert await _available(owner_engine, books.invoice) == 118_000


async def test_manual_matches_stay_inside_their_organization(
    app: FastAPI, owner_engine: AsyncEngine, books: Books
) -> None:
    other = await statement_setup(owner_engine)
    async with signed_in(app, other.member.email) as outsider:
        refused = await _create(
            outsider,
            books,
            [books.january],
            [(books.invoice, 118_000)],
            account=other.account_id,
        )

    assert refused.status_code == 404


async def test_two_manual_matches_at_once_never_overdraw_a_receivable(
    app: FastAPI, owner_engine: AsyncEngine, books: Books
) -> None:
    second_account = uuid7()
    async with owner_engine.begin() as connection:
        await connection.execute(
            text(
                """INSERT INTO bank_accounts (id, organization_id, bank, currency, alias,
                                              number_last4, created_at)
                   VALUES (:id, :org, 'BBVA', 'PEN', 'Secundaria', '9876', :now)"""
            ),
            {"id": second_account, "org": books.setup.organization_id, "now": NOW},
        )
        second_credit = await connection.scalar(
            text(
                """INSERT INTO bank_movements (id, organization_id, bank_account_id,
                                               import_file_id, booked_on, amount_cents,
                                               description, description_norm, fingerprint,
                                               doc_refs, created_at)
                   SELECT gen_random_uuid(), organization_id, :account, import_file_id,
                          booked_on, 70000, 'ABONO', 'ABONO', :fingerprint, '{}', :now
                   FROM bank_movements WHERE id = :credit
                   RETURNING id"""
            ),
            {
                "account": second_account,
                "credit": books.january,
                "fingerprint": "a" * 64,
                "now": NOW,
            },
        )
    other_analyst = await add_member(owner_engine, NOW, books.setup.organization_id, ["analyst"])
    async with (
        signed_in(app, books.setup.member.email) as first,
        signed_in(app, other_analyst.email) as second,
    ):
        responses = await asyncio.gather(
            _create(first, books, [books.february], [(books.invoice, 50_000)]),
            _create(
                second,
                books,
                [second_credit],
                [(books.invoice, 70_000)],
                account=second_account,
            ),
        )

    assert sorted(response.status_code for response in responses) == [201, 409]
    assert await _available(owner_engine, books.invoice) >= 0


async def test_open_receivables_are_searched_by_document_customer_or_tax_id(
    app: FastAPI, books: Books
) -> None:
    async with signed_in(app, books.setup.member.email) as client:

        async def search(**params: Any) -> list[str]:
            response = await client.get("/api/app/inbox/receivables", params=params)
            return [item["doc_number"] for item in response.json()["receivables"]]

        everything = await search()
        by_document = await search(q="f001-124")
        by_customer = await search(q="gloria")
        by_tax_id = await search(q="20512345678")
        await _create(client, books, [books.january], [(books.invoice, 118_000)])
        after_matching = await search()

    assert everything == ["F001-00000123", "F001-124"]
    assert (by_document, by_customer, by_tax_id) == (["F001-124"], ["F001-124"], ["F001-00000123"])
    assert after_matching == ["F001-124"]
