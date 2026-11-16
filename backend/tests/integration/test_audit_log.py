import json
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid7

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from concilia.audit.domain.events import ALLOWED_METADATA_KEYS
from tests.support.api import Member, add_member, build_app, create_member, signed_in
from tests.support.clock import FixedClock
from tests.support.database import DatabaseUrls

pytestmark = pytest.mark.anyio

NOW = datetime(2027, 2, 3, 15, 0, tzinfo=UTC)


@pytest.fixture
async def app(database: DatabaseUrls) -> AsyncIterator[FastAPI]:
    app = build_app(database.for_role("concilia_app"), FixedClock(NOW))
    yield app
    await app.state.engine.dispose()


async def _event(
    owner_engine: AsyncEngine,
    member: Member,
    action: str,
    entity: str,
    at: datetime,
    metadata: dict[str, Any] | None = None,
) -> UUID:
    event_id = uuid7()
    async with owner_engine.begin() as connection:
        await connection.execute(
            text(
                """INSERT INTO audit_events (id, organization_id, actor_user_id, action, entity,
                                             entity_id, metadata, at)
                   VALUES (:id, :org, :actor, :action, :entity, :entity_id,
                           CAST(:metadata AS jsonb), :at)"""
            ),
            {
                "id": event_id,
                "org": member.organization_ids[0],
                "actor": member.user_id,
                "action": action,
                "entity": entity,
                "entity_id": uuid7(),
                "metadata": json.dumps(metadata or {}),
                "at": at,
            },
        )
    return event_id


async def _log(app: FastAPI, member: Member, **params: Any) -> Any:
    async with signed_in(app, member.email) as client:
        return await client.get("/api/app/audit-events", params=params)


@pytest.fixture
async def team(owner_engine: AsyncEngine) -> tuple[Member, Member]:
    analyst = await create_member(owner_engine, NOW, organizations={"Andina": ["analyst"]})
    reviewer = await add_member(owner_engine, NOW, analyst.organization_ids[0], ["reviewer"])
    return analyst, reviewer


async def test_members_read_the_log_newest_first_with_who_acted(
    app: FastAPI, owner_engine: AsyncEngine, team: tuple[Member, Member]
) -> None:
    analyst, reviewer = team
    first = await _event(
        owner_engine, analyst, "import.confirmed", "import_file", datetime(2027, 1, 5, tzinfo=UTC)
    )
    second = await _event(
        owner_engine,
        reviewer,
        "member.roles_changed",
        "member",
        datetime(2027, 1, 6, tzinfo=UTC),
        {"roles": ["reviewer"]},
    )

    response = await _log(app, reviewer)

    assert response.status_code == 200
    events = [e for e in response.json()["events"] if e["id"] in {str(first), str(second)}]
    assert [(e["id"], e["action"], e["entity"], e["actor_user_id"]) for e in events] == [
        (str(second), "member.roles_changed", "member", str(reviewer.user_id)),
        (str(first), "import.confirmed", "import_file", str(analyst.user_id)),
    ]
    assert events[0]["metadata"] == {"roles": ["reviewer"]}
    assert all(event["actor_name"] for event in events)


async def test_the_log_filters_by_actor_action_entity_and_lima_day(
    app: FastAPI, owner_engine: AsyncEngine, team: tuple[Member, Member]
) -> None:
    analyst, reviewer = team
    late_on_the_4th = await _event(
        owner_engine, analyst, "match.confirmed", "match", datetime(2027, 1, 5, 4, 30, tzinfo=UTC)
    )
    on_the_5th = await _event(
        owner_engine, reviewer, "match.approved", "match", datetime(2027, 1, 5, 5, 0, tzinfo=UTC)
    )
    period = await _event(
        owner_engine,
        reviewer,
        "period.closed",
        "period_event",
        datetime(2027, 1, 6, 12, tzinfo=UTC),
    )

    async def ids(**params: Any) -> list[str]:
        return [event["id"] for event in (await _log(app, analyst, **params)).json()["events"]]

    assert await ids(actor_user_id=str(analyst.user_id)) == [str(late_on_the_4th)]
    assert await ids(action="match.approved") == [str(on_the_5th)]
    assert await ids(entity="period_event") == [str(period)]
    assert await ids(**{"from": "2027-01-04", "to": "2027-01-04"}) == [str(late_on_the_4th)]
    assert await ids(**{"from": "2027-01-05", "to": "2027-01-05"}) == [str(on_the_5th)]
    assert await ids(entity="match", **{"from": "2027-01-05"}) == [str(on_the_5th)]


async def test_the_log_pages_by_keyset(
    app: FastAPI, owner_engine: AsyncEngine, team: tuple[Member, Member]
) -> None:
    analyst, _ = team
    created = [
        await _event(
            owner_engine,
            analyst,
            "receivable.cancelled",
            "receivable",
            datetime(2027, 1, day, tzinfo=UTC),
        )
        for day in range(1, 6)
    ]
    newest = [str(event_id) for event_id in reversed(created)]

    first = (await _log(app, analyst, entity="receivable", limit=2)).json()
    second = (
        await _log(app, analyst, entity="receivable", limit=2, after=first["next_cursor"])
    ).json()
    last = (
        await _log(app, analyst, entity="receivable", limit=2, after=second["next_cursor"])
    ).json()
    back = (
        await _log(app, analyst, entity="receivable", limit=2, before=second["previous_cursor"])
    ).json()

    def page(view: dict[str, Any]) -> tuple[list[str], bool, bool]:
        return [e["id"] for e in view["events"]], view["has_previous"], view["has_next"]

    assert page(first) == (newest[0:2], False, True)
    assert page(second) == (newest[2:4], True, True)
    assert page(last) == (newest[4:5], True, False)
    assert page(back) == (newest[0:2], False, True)


async def test_the_log_stays_inside_its_organization(
    app: FastAPI, owner_engine: AsyncEngine, team: tuple[Member, Member]
) -> None:
    analyst, reviewer = team
    stranger = await create_member(owner_engine, NOW, organizations={"Beta": ["admin"]})
    await _event(owner_engine, analyst, "import.uploaded", "import_file", NOW)

    events = (await _log(app, stranger)).json()["events"]
    async with signed_in(app, stranger.email) as client:
        stranger_actors = (await client.get("/api/app/audit-events/actors")).json()
    async with signed_in(app, analyst.email) as client:
        actors = (await client.get("/api/app/audit-events/actors")).json()

    assert all(event["actor_user_id"] != str(analyst.user_id) for event in events)
    assert [actor["user_id"] for actor in stranger_actors] == [str(stranger.user_id)]
    assert {actor["user_id"] for actor in actors} == {str(analyst.user_id), str(reviewer.user_id)}


@pytest.mark.parametrize(
    ("params", "detail"),
    [
        ({"after": "abc"}, "invalid_cursor"),
        ({"from": "2027-01-05", "to": "2027-01-04"}, "invalid_range"),
    ],
)
async def test_invalid_queries_are_refused(
    app: FastAPI, team: tuple[Member, Member], params: dict[str, str], detail: str
) -> None:
    response = await _log(app, team[0], **params)

    assert (response.status_code, response.json()["detail"]) == (422, detail)


async def test_unknown_actions_and_entities_are_refused(
    app: FastAPI, team: tuple[Member, Member]
) -> None:
    assert (await _log(app, team[0], action="match.deleted")).status_code == 422
    assert (await _log(app, team[0], entity="customer")).status_code == 422


async def test_the_database_refuses_metadata_outside_the_allowed_keys(
    owner_engine: AsyncEngine, team: tuple[Member, Member]
) -> None:
    with pytest.raises(DBAPIError, match="audit_events_metadata_keys"):
        await _event(
            owner_engine, team[0], "import.uploaded", "import_file", NOW, {"filename": "x"}
        )


async def test_the_database_allows_exactly_the_domain_metadata_keys(
    owner_engine: AsyncEngine,
) -> None:
    async with owner_engine.connect() as connection:
        definition = await connection.scalar(
            text(
                """SELECT pg_get_constraintdef(oid) FROM pg_constraint
                   WHERE conname = 'audit_events_metadata_keys'"""
            )
        )

    keys = re.search(r"ARRAY\[(.*?)\]", definition)

    assert keys is not None
    assert set(re.findall(r"'(\w+)'", keys.group(1))) == ALLOWED_METADATA_KEYS
