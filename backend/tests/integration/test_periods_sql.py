from datetime import UTC, date, datetime
from uuid import UUID, uuid7

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from concilia.periods.infrastructure.sql import SqlPeriodQueries
from concilia.shared.infrastructure.db import organization_transaction
from tests.support.api import Member, create_member

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 11, 23, 14, 0, tzinfo=UTC)
JANUARY, FEBRUARY, MARCH = date(2027, 1, 1), date(2027, 2, 1), date(2027, 3, 1)


async def _account(owner_engine: AsyncEngine, member: Member) -> UUID:
    account_id = uuid7()
    async with owner_engine.begin() as connection:
        await connection.execute(
            text(
                """INSERT INTO bank_accounts (id, organization_id, bank, currency, alias,
                                              number_last4, created_at)
                   VALUES (:id, :org, 'BCP', 'PEN', 'Principal', '1234', :now)"""
            ),
            {"id": account_id, "org": member.organization_ids[0], "now": NOW},
        )
    return account_id


async def _event(
    app_engine: AsyncEngine,
    member: Member,
    account_id: UUID,
    period: date,
    action: str,
    reason: str | None = None,
) -> None:
    async with organization_transaction(app_engine, member.organization_ids[0]) as connection:
        await connection.execute(
            text(
                """INSERT INTO period_events (id, organization_id, bank_account_id, period, action,
                                             reason, decided_by, decided_at)
                   VALUES (:id, :org, :account, :period, :action, :reason, :user, :now)"""
            ),
            {
                "id": uuid7(),
                "org": member.organization_ids[0],
                "account": account_id,
                "period": period,
                "action": action,
                "reason": reason,
                "user": member.user_id,
                "now": NOW,
            },
        )


async def _closed(
    app_engine: AsyncEngine, member: Member, account_id: UUID, periods: list[date]
) -> set[date]:
    async with organization_transaction(app_engine, member.organization_ids[0]) as connection:
        return await SqlPeriodQueries(connection).closed_periods(account_id, periods)


async def test_the_last_event_decides_whether_a_period_is_closed(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    reviewer = await create_member(owner_engine, NOW, organizations={"Andina": ["reviewer"]})
    account, other_account = (
        await _account(owner_engine, reviewer),
        await _account(owner_engine, reviewer),
    )
    await _event(app_engine, reviewer, account, JANUARY, "close")
    await _event(app_engine, reviewer, account, JANUARY, "reopen", "Faltó un abono")
    await _event(app_engine, reviewer, account, FEBRUARY, "close")
    await _event(app_engine, reviewer, other_account, MARCH, "close")

    assert await _closed(app_engine, reviewer, account, [JANUARY, FEBRUARY, MARCH]) == {FEBRUARY}
    assert await _closed(app_engine, reviewer, other_account, [MARCH]) == {MARCH}
    assert await _closed(app_engine, reviewer, account, []) == set()


async def test_periods_of_another_organization_are_invisible(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    alpha = await create_member(owner_engine, NOW, organizations={"Alfa": ["reviewer"]})
    beta = await create_member(owner_engine, NOW, organizations={"Beta": ["reviewer"]})
    account = await _account(owner_engine, alpha)
    await _event(app_engine, alpha, account, JANUARY, "close")

    assert await _closed(app_engine, beta, account, [JANUARY]) == set()


@pytest.mark.parametrize(
    ("period", "action", "reason", "message"),
    [
        (JANUARY, "reopen", None, "period_events_check"),
        (date(2027, 1, 15), "close", None, "period_events_period_check"),
        (JANUARY, "approve", None, "period_events_action_check"),
    ],
)
async def test_invalid_events_are_rejected(
    owner_engine: AsyncEngine,
    app_engine: AsyncEngine,
    period: date,
    action: str,
    reason: str | None,
    message: str,
) -> None:
    reviewer = await create_member(owner_engine, NOW, organizations={"Andina": ["reviewer"]})
    account = await _account(owner_engine, reviewer)

    with pytest.raises(DBAPIError, match=message):
        await _event(app_engine, reviewer, account, period, action, reason)


@pytest.mark.parametrize(
    "statement", ["UPDATE period_events SET action = 'reopen'", "DELETE FROM period_events"]
)
async def test_period_events_are_append_only(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, statement: str
) -> None:
    reviewer = await create_member(owner_engine, NOW, organizations={"Andina": ["reviewer"]})

    with pytest.raises(DBAPIError, match="permission denied"):
        async with organization_transaction(app_engine, reviewer.organization_ids[0]) as connection:
            await connection.execute(text(statement))
