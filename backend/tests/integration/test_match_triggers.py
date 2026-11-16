from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID, uuid7

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from concilia.shared.infrastructure.db import organization_transaction
from tests.support.api import add_member
from tests.support.imports import statement_setup

pytestmark = pytest.mark.anyio

NOW = datetime(2027, 2, 3, 15, 0, tzinfo=UTC)


@dataclass(frozen=True)
class World:
    organization_id: UUID
    analyst: UUID
    reviewer: UUID
    other_reviewer: UUID
    account: UUID
    other_account: UUID
    credit: UUID
    small_credit: UUID
    february_credit: UUID
    debit: UUID
    voided_credit: UUID
    foreign_credit: UUID
    receivable: UUID
    big_receivable: UUID
    cancelled_receivable: UUID


async def _movement(
    connection: AsyncConnection,
    world: dict[str, UUID],
    account: UUID,
    booked_on: str,
    amount: int,
    voided: bool = False,
) -> UUID:
    movement = uuid7()
    await connection.execute(
        text(
            """INSERT INTO bank_movements (id, organization_id, bank_account_id, import_file_id,
                                           booked_on, amount_cents, description, description_norm,
                                           fingerprint, doc_refs, created_at, voided_at)
               VALUES (:id, :org, :account, :file, :on, :amount, 'PAGO', 'PAGO',
                       :fingerprint, '{}', :now, :voided)"""
        ),
        {
            "id": movement,
            "org": world["org"],
            "account": account,
            "file": world["file"],
            "on": date.fromisoformat(booked_on),
            "amount": amount,
            "fingerprint": movement.hex * 2,
            "now": NOW,
            "voided": NOW if voided else None,
        },
    )
    return movement


async def _receivable(
    connection: AsyncConnection, world: dict[str, UUID], amount: int, cancelled: bool = False
) -> UUID:
    receivable = uuid7()
    await connection.execute(
        text(
            """INSERT INTO receivables (id, organization_id, import_file_id, customer_name,
                                        customer_name_norm, doc_number, doc_number_norm, issued_on,
                                        due_on, amount_cents, created_at, updated_at,
                                        cancelled_at, cancel_reason)
               VALUES (:id, :org, :file, 'Cliente', 'CLIENTE', :doc, :doc, '2027-01-01',
                       '2027-01-31', :amount, :now, :now, :cancelled, :reason)"""
        ),
        {
            "id": receivable,
            "org": world["org"],
            "file": world["file"],
            "doc": f"F001-{receivable.int % 10_000_000}",
            "amount": amount,
            "now": NOW,
            "cancelled": NOW if cancelled else None,
            "reason": "Nota de crédito" if cancelled else None,
        },
    )
    return receivable


@pytest.fixture
async def world(owner_engine: AsyncEngine) -> World:
    setup = await statement_setup(owner_engine, roles=["analyst"])
    analyst, org = setup.member, setup.organization_id
    reviewer = await add_member(owner_engine, NOW, org, ["reviewer"])
    other_reviewer = await add_member(owner_engine, NOW, org, ["reviewer"])
    ids = {"org": org, "account": setup.account_id, "other_account": uuid7(), "file": uuid7()}
    async with owner_engine.begin() as connection:
        for account in (ids["other_account"],):
            await connection.execute(
                text(
                    """INSERT INTO bank_accounts (id, organization_id, bank, currency, alias,
                                                  number_last4, created_at)
                       VALUES (:id, :org, 'BCP', 'PEN', :alias, '1234', :now)"""
                ),
                {"id": account, "org": org, "alias": str(account), "now": NOW},
            )
        await connection.execute(
            text(
                """INSERT INTO import_files (id, organization_id, kind, bank_account_id,
                                             import_profile_id, profile_snapshot, filename,
                                             sha256, size_bytes, content, status, created_by,
                                             created_at)
                   VALUES (:file, :org, 'bank_statement', :account, :profile, '{}', 'enero.csv',
                           repeat('a', 64), 3, 'abc', 'confirmed', :user, :now)"""
            ),
            {
                "file": ids["file"],
                "org": org,
                "account": ids["account"],
                "profile": setup.profile_id,
                "user": analyst.user_id,
                "now": NOW,
            },
        )
        world = World(
            organization_id=org,
            analyst=analyst.user_id,
            reviewer=reviewer.user_id,
            other_reviewer=other_reviewer.user_id,
            account=ids["account"],
            other_account=ids["other_account"],
            credit=await _movement(connection, ids, ids["account"], "2027-01-05", 100_00),
            small_credit=await _movement(connection, ids, ids["account"], "2027-01-06", 50_00),
            february_credit=await _movement(connection, ids, ids["account"], "2027-02-02", 70_00),
            debit=await _movement(connection, ids, ids["account"], "2027-01-07", -20_00),
            voided_credit=await _movement(
                connection, ids, ids["account"], "2027-01-08", 30_00, voided=True
            ),
            foreign_credit=await _movement(
                connection, ids, ids["other_account"], "2027-01-09", 40_00
            ),
            receivable=await _receivable(connection, ids, 100_00),
            big_receivable=await _receivable(connection, ids, 200_00),
            cancelled_receivable=await _receivable(connection, ids, 10_00, cancelled=True),
        )
        await connection.execute(
            text(
                """INSERT INTO period_events (id, organization_id, bank_account_id, period, action,
                                              decided_by, decided_at)
                   VALUES (:id, :org, :account, '2027-02-01', 'close', :user, :now)"""
            ),
            {
                "id": uuid7(),
                "org": org,
                "account": ids["account"],
                "user": reviewer.user_id,
                "now": NOW,
            },
        )
    return world


async def _match(
    connection: AsyncConnection,
    world: World,
    credits: list[UUID],
    applications: list[tuple[UUID, int]],
    account: UUID | None = None,
) -> UUID:
    match = uuid7()
    await connection.execute(
        text(
            """INSERT INTO matches (id, organization_id, bank_account_id, source, created_by,
                                    created_at)
               VALUES (:id, :org, :account, 'manual', :user, :now)"""
        ),
        {
            "id": match,
            "org": world.organization_id,
            "account": account or world.account,
            "user": world.analyst,
            "now": NOW,
        },
    )
    for credit in credits:
        await connection.execute(
            text(
                """INSERT INTO match_items (id, organization_id, match_id, bank_movement_id)
                   VALUES (:id, :org, :match, :credit)"""
            ),
            {"id": uuid7(), "org": world.organization_id, "match": match, "credit": credit},
        )
    for receivable, applied in applications:
        await connection.execute(
            text(
                """INSERT INTO match_items (id, organization_id, match_id, receivable_id,
                                            applied_cents)
                   VALUES (:id, :org, :match, :receivable, :applied)"""
            ),
            {
                "id": uuid7(),
                "org": world.organization_id,
                "match": match,
                "receivable": receivable,
                "applied": applied,
            },
        )
    return match


async def _decide(
    connection: AsyncConnection,
    world: World,
    match: UUID,
    action: str,
    by: UUID,
    reason: str | None = None,
    difference_reason: str | None = None,
) -> None:
    await connection.execute(
        text(
            """INSERT INTO match_decisions (id, organization_id, match_id, action, reason,
                                            difference_reason, decided_by, decided_at)
               VALUES (:id, :org, :match, :action, :reason, :difference_reason, :by, :now)"""
        ),
        {
            "id": uuid7(),
            "org": world.organization_id,
            "match": match,
            "action": action,
            "reason": reason,
            "difference_reason": difference_reason,
            "by": by,
            "now": NOW,
        },
    )


async def _confirmed(app_engine: AsyncEngine, world: World) -> UUID:
    async with organization_transaction(app_engine, world.organization_id) as connection:
        match = await _match(connection, world, [world.credit], [(world.receivable, 100_00)])
        await _decide(connection, world, match, "confirm", world.analyst)
    return match


async def test_a_match_needs_a_credit_and_a_receivable(
    app_engine: AsyncEngine, world: World
) -> None:
    with pytest.raises(DBAPIError, match="match_needs_a_credit_and_a_receivable"):
        async with organization_transaction(app_engine, world.organization_id) as connection:
            await _match(connection, world, [], [(world.receivable, 100_00)])


@pytest.mark.parametrize("movement", ["debit", "voided_credit", "foreign_credit"])
async def test_only_live_credits_of_the_match_account_can_be_matched(
    app_engine: AsyncEngine, world: World, movement: str
) -> None:
    with pytest.raises(DBAPIError, match="not_a_live_credit_of_the_account"):
        async with organization_transaction(app_engine, world.organization_id) as connection:
            await _match(connection, world, [getattr(world, movement)], [(world.receivable, 1)])


async def test_a_credit_is_in_one_active_match_at_most(
    app_engine: AsyncEngine, world: World
) -> None:
    async with organization_transaction(app_engine, world.organization_id) as connection:
        first = await _match(connection, world, [world.credit], [(world.receivable, 100_00)])
    with pytest.raises(DBAPIError, match="credit_in_active_match"):
        async with organization_transaction(app_engine, world.organization_id) as connection:
            await _match(connection, world, [world.credit], [(world.big_receivable, 100_00)])
    async with organization_transaction(app_engine, world.organization_id) as connection:
        await _decide(connection, world, first, "discard", world.analyst)
        await _match(connection, world, [world.credit], [(world.big_receivable, 100_00)])


async def test_applied_amounts_never_exceed_the_available_balance(
    app_engine: AsyncEngine, world: World
) -> None:
    async with organization_transaction(app_engine, world.organization_id) as connection:
        await _match(connection, world, [world.credit], [(world.big_receivable, 150_00)])
    with pytest.raises(DBAPIError, match="applied_exceeds_available"):
        async with organization_transaction(app_engine, world.organization_id) as connection:
            await _match(connection, world, [world.small_credit], [(world.big_receivable, 50_01)])
    async with organization_transaction(app_engine, world.organization_id) as connection:
        await _match(connection, world, [world.small_credit], [(world.big_receivable, 50_00)])
        balance = (
            await connection.execute(
                text(
                    """SELECT open_cents, available_cents FROM receivable_balances
                       WHERE receivable_id = :id"""
                ),
                {"id": world.big_receivable},
            )
        ).one()
    assert tuple(balance) == (200_00, 0)


async def test_cancelled_receivables_cannot_be_matched(
    app_engine: AsyncEngine, world: World
) -> None:
    with pytest.raises(DBAPIError, match="receivable_cancelled"):
        async with organization_transaction(app_engine, world.organization_id) as connection:
            await _match(connection, world, [world.credit], [(world.cancelled_receivable, 1)])


async def test_items_cannot_be_added_after_a_decision(
    app_engine: AsyncEngine, world: World
) -> None:
    match = await _confirmed(app_engine, world)

    with pytest.raises(DBAPIError, match="match_already_decided"):
        async with organization_transaction(app_engine, world.organization_id) as connection:
            await connection.execute(
                text(
                    """INSERT INTO match_items (id, organization_id, match_id, bank_movement_id)
                       VALUES (:id, :org, :match, :credit)"""
                ),
                {
                    "id": uuid7(),
                    "org": world.organization_id,
                    "match": match,
                    "credit": world.small_credit,
                },
            )


@pytest.mark.parametrize(
    ("before", "action"),
    [
        ([], "approve"),
        ([], "revert"),
        (["confirm"], "confirm"),
        (["confirm"], "discard"),
        (["confirm"], "revert"),
        (["discard"], "confirm"),
        (["confirm", "reject"], "approve"),
    ],
)
async def test_decisions_follow_the_state_table(
    app_engine: AsyncEngine, world: World, before: list[str], action: str
) -> None:
    async with organization_transaction(app_engine, world.organization_id) as connection:
        match = await _match(connection, world, [world.credit], [(world.receivable, 100_00)])
        for previous in before:
            by = world.analyst if previous in {"confirm", "discard"} else world.reviewer
            await _decide(connection, world, match, previous, by, reason="Motivo")

    with pytest.raises(DBAPIError, match="invalid_transition"):
        async with organization_transaction(app_engine, world.organization_id) as connection:
            await _decide(connection, world, match, action, world.other_reviewer, reason="Motivo")


@pytest.mark.parametrize("action", ["approve", "reject"])
async def test_who_created_or_confirmed_a_match_never_decides_on_it(
    app_engine: AsyncEngine, world: World, action: str
) -> None:
    match = await _confirmed(app_engine, world)

    with pytest.raises(DBAPIError, match="four_eyes"):
        async with organization_transaction(app_engine, world.organization_id) as connection:
            await _decide(connection, world, match, action, world.analyst, reason="Motivo")
    async with organization_transaction(app_engine, world.organization_id) as connection:
        await _decide(connection, world, match, action, world.reviewer, reason="Motivo")


async def test_whoever_confirmed_an_engine_proposal_cannot_approve_it(
    app_engine: AsyncEngine, world: World
) -> None:
    async with organization_transaction(app_engine, world.organization_id) as connection:
        run, match = uuid7(), uuid7()
        params = {
            "run": run,
            "match": match,
            "org": world.organization_id,
            "account": world.account,
            "now": NOW,
        }
        await connection.execute(
            text(
                """INSERT INTO engine_runs (id, organization_id, bank_account_id, period,
                                            rules_version, started_at)
                   VALUES (:run, :org, :account, '2027-01-01', 1, :now)"""
            ),
            params,
        )
        await connection.execute(
            text(
                """INSERT INTO matches (id, organization_id, bank_account_id, source, rule, score,
                                        explanation, engine_run_id, created_at)
                   VALUES (:match, :org, :account, 'engine', 'R1', 100, 'Exacta', :run, :now)"""
            ),
            params,
        )
        for column, value, applied in (
            ("bank_movement_id", world.credit, None),
            ("receivable_id", world.receivable, 100_00),
        ):
            await connection.execute(
                text(
                    f"""INSERT INTO match_items (id, organization_id, match_id, {column},
                                                 applied_cents)
                        VALUES (:id, :org, :match, :value, :applied)"""
                ),
                {
                    "id": uuid7(),
                    "org": world.organization_id,
                    "match": match,
                    "value": value,
                    "applied": applied,
                },
            )
        await _decide(connection, world, match, "confirm", world.reviewer)

    with pytest.raises(DBAPIError, match="four_eyes"):
        async with organization_transaction(app_engine, world.organization_id) as connection:
            await _decide(connection, world, match, "approve", world.reviewer)
    async with organization_transaction(app_engine, world.organization_id) as connection:
        await _decide(connection, world, match, "approve", world.other_reviewer)


async def test_matches_in_a_closed_period_take_no_actions(
    app_engine: AsyncEngine, world: World
) -> None:
    async with organization_transaction(app_engine, world.organization_id) as connection:
        match = await _match(
            connection, world, [world.february_credit], [(world.big_receivable, 70_00)]
        )

    with pytest.raises(DBAPIError, match="closed_period"):
        async with organization_transaction(app_engine, world.organization_id) as connection:
            await _decide(connection, world, match, "discard", world.analyst)


@pytest.mark.parametrize(
    ("applied", "difference_reason", "error"),
    [
        (99_00, None, "difference_reason_mismatch"),
        (100_00, "rounding", "difference_reason_mismatch"),
        (100_00, None, None),
        (99_00, "commission", None),
        (99_00, "overpayment", None),
    ],
)
async def test_confirming_a_difference_needs_a_reason(
    app_engine: AsyncEngine,
    world: World,
    applied: int,
    difference_reason: str | None,
    error: str | None,
) -> None:
    async with organization_transaction(app_engine, world.organization_id) as connection:
        match = await _match(connection, world, [world.credit], [(world.big_receivable, applied)])

    async def confirm() -> None:
        async with organization_transaction(app_engine, world.organization_id) as connection:
            await _decide(
                connection,
                world,
                match,
                "confirm",
                world.analyst,
                difference_reason=difference_reason,
            )

    if error is None:
        await confirm()
    else:
        with pytest.raises(DBAPIError, match=error):
            await confirm()


async def test_an_overpayment_is_a_positive_difference(
    app_engine: AsyncEngine, world: World
) -> None:
    async with organization_transaction(app_engine, world.organization_id) as connection:
        match = await _match(
            connection,
            world,
            [world.credit, world.small_credit],
            [(world.big_receivable, 160_00)],
        )

    with pytest.raises(DBAPIError, match="overpayment_not_positive"):
        async with organization_transaction(app_engine, world.organization_id) as connection:
            await _decide(
                connection, world, match, "confirm", world.analyst, difference_reason="overpayment"
            )


async def test_status_and_balances_follow_the_last_decision(
    app_engine: AsyncEngine, world: World
) -> None:
    match = await _confirmed(app_engine, world)

    async def snapshot() -> tuple[str, int, int]:
        async with organization_transaction(app_engine, world.organization_id) as connection:
            row = (
                await connection.execute(
                    text(
                        """SELECT s.status, b.open_cents, b.available_cents
                           FROM match_status s, receivable_balances b
                           WHERE s.match_id = :match AND b.receivable_id = :receivable"""
                    ),
                    {"match": match, "receivable": world.receivable},
                )
            ).one()
        return row.status, row.open_cents, row.available_cents

    assert await snapshot() == ("confirmed", 100_00, 0)
    async with organization_transaction(app_engine, world.organization_id) as connection:
        await _decide(connection, world, match, "approve", world.reviewer)
    assert await snapshot() == ("approved", 0, 0)
    async with organization_transaction(app_engine, world.organization_id) as connection:
        await _decide(connection, world, match, "revert", world.other_reviewer, reason="Error")
    assert await snapshot() == ("reverted", 100_00, 100_00)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE matches SET explanation = 'x'",
        "DELETE FROM match_items",
        "UPDATE match_decisions SET reason = 'x'",
        "DELETE FROM match_decisions",
    ],
)
async def test_match_history_is_insert_only_for_the_app(
    app_engine: AsyncEngine, world: World, sql: str
) -> None:
    await _confirmed(app_engine, world)

    with pytest.raises(DBAPIError, match="permission denied"):
        async with organization_transaction(app_engine, world.organization_id) as connection:
            await connection.execute(text(sql))
