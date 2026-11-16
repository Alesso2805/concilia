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
from tests.support.matches import insert_match

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
class Team:
    setup: Setup
    reviewer: Member
    other_reviewer: Member
    both: Member

    @property
    def analyst(self) -> Member:
        return self.setup.member


async def _confirmed_import(
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
async def team(
    app: FastAPI, owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> Team:
    setup = await statement_setup(owner_engine)
    organization_id = setup.organization_id
    team = Team(
        setup,
        await add_member(owner_engine, NOW, organization_id, ["reviewer"]),
        await add_member(owner_engine, NOW, organization_id, ["reviewer"]),
        await add_member(owner_engine, NOW, organization_id, ["analyst", "reviewer"]),
    )
    profile_id = await receivables_profile(owner_engine, setup)
    async with signed_in(app, setup.member.email) as client:
        await _confirmed_import(client, setup, worker_engine, clock, STATEMENT)
        await _confirmed_import(client, setup, worker_engine, clock, RECEIVABLES, profile_id)
        for period in ("2027-01-01", "2027-02-01"):
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
    return team


async def _proposals(client: httpx.AsyncClient, setup: Setup, period: str) -> list[str]:
    response = await client.get(
        "/api/app/matches",
        params={"bank_account_id": str(setup.account_id), "period": period},
    )
    return [match["id"] for match in response.json()["matches"]]


async def _decide(
    client: httpx.AsyncClient, match_id: str, action: str, **fields: Any
) -> httpx.Response:
    return await client.post(
        f"/api/app/matches/{match_id}/decisions",
        json={"id": fields.pop("id", None) or client_id(), "action": action, **fields},
        headers=xsrf_header(client),
    )


async def _detail(client: httpx.AsyncClient, match_id: str) -> dict[str, Any]:
    detail: dict[str, Any] = (await client.get(f"/api/app/matches/{match_id}")).json()
    return detail


async def test_an_analyst_confirms_and_another_person_approves(
    app: FastAPI, owner_engine: AsyncEngine, team: Team
) -> None:
    decision_id = client_id()
    async with signed_in(app, team.analyst.email) as analyst:
        [match] = await _proposals(analyst, team.setup, "2027-01-01")
        confirmed = await _decide(analyst, match, "confirm", id=decision_id)
        replay = await _decide(analyst, match, "confirm", id=decision_id)
        reused = await _decide(analyst, match, "discard", id=decision_id)
        not_mine = await _decide(analyst, match, "approve")
    async with signed_in(app, team.reviewer.email) as reviewer:
        approved = await _decide(reviewer, match, "approve")
        detail = await _detail(reviewer, match)

    assert (confirmed.status_code, replay.status_code) == (201, 200)
    assert replay.json() == confirmed.json()
    assert (reused.status_code, reused.json()["detail"]) == (409, "id_conflict")
    assert (not_mine.status_code, not_mine.json()["detail"]) == (403, "role_required")
    assert approved.status_code == 201
    assert detail["status"] == "approved"
    assert [item["available_cents"] for item in detail["receivables"]] == [0]
    assert [d["action"] for d in detail["decisions"]] == ["confirm", "approve"]
    async with owner_engine.connect() as connection:
        actions = list(
            await connection.scalars(
                text(
                    """SELECT action FROM audit_events
                       WHERE organization_id = :org AND entity = 'match' ORDER BY seq"""
                ),
                {"org": team.setup.organization_id},
            )
        )
        open_cents = await connection.scalar(
            text(
                """SELECT b.open_cents FROM receivable_balances b
                   JOIN receivables r ON r.id = b.receivable_id
                   WHERE r.organization_id = :org AND r.doc_number_norm = 'F001-123'"""
            ),
            {"org": team.setup.organization_id},
        )
    assert actions == ["match.confirmed", "match.approved"]
    assert open_cents == 0


async def test_nobody_approves_what_they_confirmed(app: FastAPI, team: Team) -> None:
    async with signed_in(app, team.both.email) as both:
        [match] = await _proposals(both, team.setup, "2027-01-01")
        await _decide(both, match, "confirm")
        own = await _decide(both, match, "approve")
        rejected_own = await _decide(both, match, "reject", reason="No corresponde")

    assert (own.status_code, own.json()["detail"]) == (409, "four_eyes")
    assert (rejected_own.status_code, rejected_own.json()["detail"]) == (409, "four_eyes")


async def test_rejecting_and_reverting_need_a_reason_and_free_the_items(
    app: FastAPI, team: Team
) -> None:
    async with signed_in(app, team.analyst.email) as analyst:
        [january] = await _proposals(analyst, team.setup, "2027-01-01")
        [february] = await _proposals(analyst, team.setup, "2027-02-01")
        for match in (january, february):
            await _decide(analyst, match, "confirm")
    async with signed_in(app, team.reviewer.email) as reviewer:
        no_reason = await _decide(reviewer, january, "reject")
        rejected = await _decide(reviewer, january, "reject", reason="El abono es de otro cliente")
        await _decide(reviewer, february, "approve")
        reverted = await _decide(reviewer, february, "revert", reason="Se aprobó por error")
    async with signed_in(app, team.other_reviewer.email) as other:
        twice = await _decide(other, february, "revert", reason="Otra vez")
        counts = (
            await other.get(
                "/api/app/inbox/counts",
                params={"bank_account_id": str(team.setup.account_id), "period": "2027-02-01"},
            )
        ).json()
        detail = await _detail(other, february)

    assert (no_reason.status_code, no_reason.json()["detail"]) == (422, "reason_required")
    assert (rejected.status_code, reverted.status_code) == (201, 201)
    assert (twice.status_code, twice.json()["detail"]) == (409, "wrong_state")
    assert counts == {"free": 1, "proposed": 0, "confirmed": 0, "approved": 0}
    assert detail["status"] == "reverted"
    assert [item["available_cents"] for item in detail["receivables"]] == [50_000]


async def test_a_difference_is_confirmed_with_a_reason_that_fits_it(
    app: FastAPI, owner_engine: AsyncEngine, team: Team
) -> None:
    async with signed_in(app, team.analyst.email) as analyst:
        [engine_match] = await _proposals(analyst, team.setup, "2027-02-01")
        await _decide(analyst, engine_match, "discard")
    async with owner_engine.connect() as connection:
        credit, receivable = (
            await connection.execute(
                text(
                    """SELECT (SELECT id FROM bank_movements
                               WHERE organization_id = :org AND amount_cents = 50000),
                              (SELECT id FROM receivables
                               WHERE organization_id = :org AND doc_number_norm = 'F001-124')"""
                ),
                {"org": team.setup.organization_id},
            )
        ).one()
    match = await insert_match(
        owner_engine,
        organization_id=team.setup.organization_id,
        bank_account_id=team.setup.account_id,
        created_by=team.reviewer.user_id,
        credits=[credit],
        applications=[(receivable, 49_000)],
        at=NOW,
    )
    async with signed_in(app, team.analyst.email) as analyst:
        missing = await _decide(analyst, str(match), "confirm")
        negative = await _decide(analyst, str(match), "confirm", difference_reason="other")
        confirmed = await _decide(analyst, str(match), "confirm", difference_reason="commission")

    assert (missing.status_code, missing.json()["detail"]) == (422, "difference_reason")
    assert (negative.status_code, negative.json()["detail"]) == (422, "difference_reason")
    assert (confirmed.status_code, confirmed.json()["difference_reason"]) == (201, "commission")


async def test_nothing_is_decided_in_a_closed_month(
    app: FastAPI, owner_engine: AsyncEngine, team: Team
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
                "org": team.setup.organization_id,
                "account": team.setup.account_id,
                "user": team.reviewer.user_id,
                "now": NOW,
            },
        )
    async with signed_in(app, team.analyst.email) as analyst:
        [match] = await _proposals(analyst, team.setup, "2027-01-01")
        refused = await _decide(analyst, match, "confirm")

    assert (refused.status_code, refused.json()["detail"]) == (409, "closed_period")


async def test_decisions_stay_inside_their_organization(
    app: FastAPI, owner_engine: AsyncEngine, team: Team
) -> None:
    other = await statement_setup(owner_engine, roles=["analyst", "reviewer"])
    async with signed_in(app, team.analyst.email) as analyst:
        [match] = await _proposals(analyst, team.setup, "2027-01-01")
    async with signed_in(app, other.member.email) as outsider:
        refused = await _decide(outsider, match, "confirm")

    assert (refused.status_code, refused.json()["detail"]) == (404, "not_found")


async def test_two_reviewers_approving_the_same_match_at_once_record_one_approval(
    app: FastAPI, team: Team
) -> None:
    async with signed_in(app, team.analyst.email) as analyst:
        [match] = await _proposals(analyst, team.setup, "2027-01-01")
        await _decide(analyst, match, "confirm")
    async with (
        signed_in(app, team.reviewer.email) as first,
        signed_in(app, team.other_reviewer.email) as second,
    ):
        responses = await asyncio.gather(
            _decide(first, match, "approve"), _decide(second, match, "approve")
        )

    assert sorted(response.status_code for response in responses) == [201, 409]


async def test_two_accounts_approved_at_once_on_one_receivable_keep_its_balance(
    app: FastAPI, owner_engine: AsyncEngine, team: Team
) -> None:
    organization_id = team.setup.organization_id
    second_account = uuid7()
    async with owner_engine.begin() as connection:
        await connection.execute(
            text(
                """INSERT INTO bank_accounts (id, organization_id, bank, currency, alias,
                                              number_last4, created_at)
                   VALUES (:id, :org, 'BBVA', 'PEN', 'Secundaria', '9876', :now)"""
            ),
            {"id": second_account, "org": organization_id, "now": NOW},
        )
        for account, amount in ((team.setup.account_id, 20_000), (second_account, 30_000)):
            await connection.execute(
                text(
                    """INSERT INTO bank_movements (id, organization_id, bank_account_id,
                                                   import_file_id, booked_on, amount_cents,
                                                   description, description_norm, fingerprint,
                                                   doc_refs, created_at)
                       SELECT gen_random_uuid(), :org, :account, import_file_id, booked_on,
                              :amount, 'ABONO PARCIAL', 'ABONO PARCIAL', :fingerprint, '{}', :now
                       FROM bank_movements
                       WHERE organization_id = :org AND amount_cents = 50000"""
                ),
                {
                    "org": organization_id,
                    "account": account,
                    "amount": amount,
                    "fingerprint": f"{account.hex}{amount:032d}",
                    "now": NOW,
                },
            )
        credits: dict[UUID, UUID] = dict(
            (
                await connection.execute(
                    text(
                        """SELECT bank_account_id, id FROM bank_movements
                           WHERE organization_id = :org AND amount_cents IN (20000, 30000)"""
                    ),
                    {"org": organization_id},
                )
            ).all()
        )
        receivable = await connection.scalar(
            text(
                """SELECT id FROM receivables
                   WHERE organization_id = :org AND doc_number_norm = 'F001-124'"""
            ),
            {"org": organization_id},
        )
    async with signed_in(app, team.analyst.email) as analyst:
        [engine_match] = await _proposals(analyst, team.setup, "2027-02-01")
        await _decide(analyst, engine_match, "discard")
    matches = [
        await insert_match(
            owner_engine,
            organization_id=organization_id,
            bank_account_id=account,
            created_by=team.analyst.user_id,
            credits=[credits[account]],
            applications=[(receivable, applied)],
            decisions=[("confirm", team.analyst.user_id)],
            at=NOW,
        )
        for account, applied in ((team.setup.account_id, 20_000), (second_account, 30_000))
    ]
    async with (
        signed_in(app, team.reviewer.email) as first,
        signed_in(app, team.other_reviewer.email) as second,
    ):
        responses = await asyncio.gather(
            _decide(first, str(matches[0]), "approve"),
            _decide(second, str(matches[1]), "approve"),
        )
    async with owner_engine.connect() as connection:
        balance = (
            await connection.execute(
                text(
                    """SELECT open_cents, available_cents FROM receivable_balances
                       WHERE receivable_id = :id"""
                ),
                {"id": receivable},
            )
        ).one()

    assert [response.status_code for response in responses] == [201, 201]
    assert tuple(balance) == (0, 0)


async def test_approving_and_rejecting_at_once_records_only_one_decision(
    app: FastAPI, owner_engine: AsyncEngine, team: Team
) -> None:
    async with signed_in(app, team.analyst.email) as analyst:
        [match] = await _proposals(analyst, team.setup, "2027-01-01")
        await _decide(analyst, match, "confirm")
    async with (
        signed_in(app, team.reviewer.email) as first,
        signed_in(app, team.other_reviewer.email) as second,
    ):
        responses = await asyncio.gather(
            _decide(first, match, "approve"),
            _decide(second, match, "reject", reason="El abono es de otro cliente"),
        )
    async with owner_engine.connect() as connection:
        actions = list(
            await connection.scalars(
                text("SELECT action FROM match_decisions WHERE match_id = :id ORDER BY seq"),
                {"id": match},
            )
        )

    assert sorted(response.status_code for response in responses) == [201, 409]
    assert actions[0] == "confirm"
    assert len(actions) == 2
    assert actions[1] in {"approve", "reject"}


async def _batch(client: httpx.AsyncClient, team: Team, action: str, period: str) -> httpx.Response:
    return await client.post(
        "/api/app/matches/batch",
        json={"action": action, "bank_account_id": str(team.setup.account_id), "period": period},
        headers=xsrf_header(client),
    )


async def test_score_100_matches_are_confirmed_and_approved_in_batch_by_two_people(
    app: FastAPI, team: Team
) -> None:
    async with signed_in(app, team.analyst.email) as analyst:
        january = await _batch(analyst, team, "confirm", "2027-01-01")
        february = await _batch(analyst, team, "confirm", "2027-02-01")
        again = await _batch(analyst, team, "confirm", "2027-01-01")
        not_mine = await _batch(analyst, team, "approve", "2027-01-01")
        mid_month = await _batch(analyst, team, "confirm", "2027-01-15")
    async with signed_in(app, team.reviewer.email) as reviewer:
        approved = await _batch(reviewer, team, "approve", "2027-01-01")
        counts = (
            await reviewer.get(
                "/api/app/inbox/counts",
                params={"bank_account_id": str(team.setup.account_id), "period": "2027-01-01"},
            )
        ).json()

    assert january.json() == {"decided": 1, "skipped": 0}
    assert february.json() == {"decided": 0, "skipped": 0}
    assert again.json() == {"decided": 0, "skipped": 0}
    assert (not_mine.status_code, not_mine.json()["detail"]) == (403, "role_required")
    assert (mid_month.status_code, mid_month.json()["detail"]) == (422, "invalid_period")
    assert approved.json() == {"decided": 1, "skipped": 0}
    assert (counts["confirmed"], counts["approved"]) == (0, 1)


async def test_a_batch_approval_leaves_what_the_reviewer_confirmed_to_someone_else(
    app: FastAPI, team: Team
) -> None:
    async with signed_in(app, team.both.email) as both:
        await _batch(both, team, "confirm", "2027-01-01")
        result = await _batch(both, team, "approve", "2027-01-01")

    assert result.json() == {"decided": 0, "skipped": 1}
