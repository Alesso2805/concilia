from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4, uuid7

import httpx
import pytest
import time_machine
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from concilia.cli import create_organization
from concilia.identity.application.registration import Registration
from tests.support.api import PASSWORD, api_client, build_app, create_member
from tests.support.clock import FixedClock
from tests.support.database import DatabaseUrls

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 11, 23, 14, 0, tzinfo=UTC)


def _client_id(at: datetime = NOW) -> UUID:
    with time_machine.travel(at, tick=False):
        return uuid7()


def _body(organization_id: UUID, **changes: str) -> dict[str, Any]:
    suffix = str(organization_id)[-12:]
    return {
        "id": str(organization_id),
        "organization_name": "Comercial Andina",
        "display_name": "Ana Admin",
        "email": f"ana-{suffix}@example.test",
        "password": PASSWORD,
        **changes,
    }


@pytest.fixture
async def client(database: DatabaseUrls) -> AsyncIterator[httpx.AsyncClient]:
    app = build_app(database.for_role("concilia_app"), FixedClock(NOW), registration_enabled=True)
    async with api_client(app) as client:
        yield client


async def _audit_sources(owner_engine: AsyncEngine, organization_id: UUID) -> list[str]:
    async with owner_engine.connect() as connection:
        result = await connection.execute(
            text(
                """SELECT metadata ->> 'source' FROM audit_events
                   WHERE organization_id = :org AND action = 'organization.created'"""
            ),
            {"org": organization_id},
        )
        return list(result.scalars())


async def test_registration_creates_an_organization_with_its_admin(
    client: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    organization_id = _client_id()
    body = _body(organization_id)

    response = await client.post("/api/public/registrations", json=body)
    login = await client.post(
        "/api/public/login", json={"email": body["email"], "password": PASSWORD}
    )

    assert (response.status_code, response.json()) == (
        201,
        {"organization_id": str(organization_id)},
    )
    assert login.json()["organizations"][0]["roles"] == ["admin"]
    assert await _audit_sources(owner_engine, organization_id) == ["registration"]


async def test_resending_the_same_registration_returns_it_without_duplicates(
    client: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    organization_id = _client_id()
    first = await client.post("/api/public/registrations", json=_body(organization_id))

    again = await client.post("/api/public/registrations", json=_body(organization_id))

    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json() == first.json()
    assert len(await _audit_sources(owner_engine, organization_id)) == 1


async def test_same_id_with_different_content_conflicts(client: httpx.AsyncClient) -> None:
    organization_id = _client_id()
    await client.post("/api/public/registrations", json=_body(organization_id))

    response = await client.post(
        "/api/public/registrations", json=_body(organization_id, organization_name="Otra")
    )

    assert (response.status_code, response.json()) == (409, {"detail": "id_conflict"})


async def test_id_of_another_organization_conflicts(
    client: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    with time_machine.travel(NOW, tick=False):
        other = await create_member(owner_engine, NOW, organizations={"Ajena": ["admin"]})

    response = await client.post("/api/public/registrations", json=_body(other.organization_ids[0]))

    assert (response.status_code, response.json()) == (409, {"detail": "id_conflict"})


@pytest.mark.parametrize(
    ("organization_id", "code"),
    [
        (uuid4(), "id_not_uuid7"),
        (_client_id(NOW - timedelta(days=2)), "id_clock_skew"),
    ],
)
async def test_ids_that_are_not_recent_uuid7_are_rejected(
    client: httpx.AsyncClient, organization_id: UUID, code: str
) -> None:
    response = await client.post("/api/public/registrations", json=_body(organization_id))

    assert (response.status_code, response.json()) == (422, {"detail": code})


async def test_an_email_already_in_use_conflicts(
    client: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    existing = await create_member(owner_engine, NOW, organizations={"Ajena": ["admin"]})

    response = await client.post(
        "/api/public/registrations", json=_body(_client_id(), email=existing.email)
    )

    assert (response.status_code, response.json()) == (409, {"detail": "email_taken"})


async def test_registration_is_off_unless_enabled(database: DatabaseUrls) -> None:
    async with api_client(build_app(database.for_role("concilia_app"), FixedClock(NOW))) as client:
        response = await client.post("/api/public/registrations", json=_body(_client_id()))

    assert response.status_code == 404


async def test_create_org_command_creates_an_organization_as_owner(
    database: DatabaseUrls, owner_engine: AsyncEngine
) -> None:
    organization_id = _client_id()
    command = Registration(
        organization_id,
        "Distribuidora Sur",
        "Luis Admin",
        f"luis-{organization_id}@example.test",
        PASSWORD,
    )

    created = await create_organization(
        database.for_role("concilia_owner"), command, FixedClock(NOW)
    )

    assert created == organization_id
    assert await _audit_sources(owner_engine, organization_id) == ["cli"]
