import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4, uuid7

import httpx
import pytest
import time_machine
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.support.api import (
    PASSWORD,
    Member,
    add_member,
    build_app,
    create_member,
    signed_in,
    xsrf_header,
)
from tests.support.clock import FixedClock
from tests.support.database import DatabaseUrls

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 11, 23, 14, 0, tzinfo=UTC)


def _client_id() -> UUID:
    with time_machine.travel(NOW, tick=False):
        return uuid7()


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
async def app(database: DatabaseUrls, clock: FixedClock) -> AsyncIterator[FastAPI]:
    app = build_app(database.for_role("concilia_app"), clock)
    yield app
    await app.state.engine.dispose()


@pytest.fixture
async def admin(owner_engine: AsyncEngine) -> Member:
    return await create_member(owner_engine, NOW, organizations={"Andina": ["admin"]})


async def _post(client: httpx.AsyncClient, url: str, body: Any = None) -> httpx.Response:
    return await client.post(url, json=body, headers=xsrf_header(client))


async def _invite(
    client: httpx.AsyncClient, email: str, roles: list[str], invitation_id: UUID | None = None
) -> httpx.Response:
    body = {"id": str(invitation_id or _client_id()), "email": email, "roles": roles}
    return await _post(client, "/api/app/invitations", body)


async def _new_account(app: FastAPI, token: str, email: str) -> httpx.Response:
    async with signed_in(app) as visitor:
        return await visitor.post(
            "/api/public/invitations/accept",
            json={"token": token, "email": email, "display_name": "Nueva", "password": PASSWORD},
        )


async def _actions(owner_engine: AsyncEngine, organization_id: UUID) -> list[tuple[str, Any]]:
    async with owner_engine.connect() as connection:
        rows = await connection.execute(
            text(
                """SELECT action, metadata FROM audit_events
                   WHERE organization_id = :org ORDER BY seq"""
            ),
            {"org": organization_id},
        )
        return [(row.action, dict(row.metadata)) for row in rows]


async def _admins(owner_engine: AsyncEngine, organization_id: UUID) -> int:
    async with owner_engine.connect() as connection:
        count = await connection.scalar(
            text(
                """SELECT count(*) FROM member_roles r JOIN memberships m USING (organization_id,
                   user_id) WHERE r.organization_id = :org AND r.role = 'admin'
                   AND m.removed_at IS NULL"""
            ),
            {"org": organization_id},
        )
        return int(count or 0)


async def test_an_invitee_creates_an_account_and_joins_with_the_invited_roles(
    app: FastAPI, admin: Member, owner_engine: AsyncEngine
) -> None:
    organization_id = admin.organization_ids[0]
    email = f"nueva-{uuid7()}@example.test"
    async with signed_in(app, admin.email) as client:
        created = await _invite(client, email.upper(), ["analyst"])
        assert created.status_code == 201
        token = created.json()["token"]
        assert created.json()["invitation"]["email"] == email
        team = (await client.get("/api/app/team")).json()
        assert [i["email"] for i in team["invitations"]] == [email]

        async with signed_in(app) as visitor:
            accepted = await visitor.post(
                "/api/public/invitations/accept",
                json={
                    "token": token,
                    "email": email,
                    "display_name": "Nueva",
                    "password": PASSWORD,
                },
            )
            assert accepted.status_code == 200
            assert accepted.json()["organization_id"] == str(organization_id)
            session = (await visitor.get("/api/app/session")).json()
            assert session["roles"] == ["analyst"]

        team = (await client.get("/api/app/team")).json()
    assert team["invitations"] == []
    assert sorted(m["email"] for m in team["members"]) == sorted([admin.email, email])
    actions = await _actions(owner_engine, organization_id)
    assert ("invitation.created", {"roles": ["analyst"]}) in actions
    assert ("invitation.accepted", {"roles": ["analyst"]}) in actions


async def test_creating_an_invitation_is_idempotent_on_its_id(
    app: FastAPI, admin: Member, owner_engine: AsyncEngine
) -> None:
    other = await create_member(owner_engine, NOW, organizations={"Beta": ["admin"]})
    invitation_id = _client_id()
    async with signed_in(app, admin.email) as client:
        first = await _invite(client, "ana@example.test", ["reviewer"], invitation_id)
        replay = await _invite(client, "ana@example.test", ["reviewer"], invitation_id)
        changed = await _invite(client, "otra@example.test", ["reviewer"], invitation_id)
    async with signed_in(app, other.email) as client:
        elsewhere = await _invite(client, "ana@example.test", ["reviewer"], invitation_id)

    assert (first.status_code, replay.status_code) == (201, 200)
    assert replay.json()["token"] is None
    assert replay.json()["invitation"] == first.json()["invitation"]
    assert (changed.status_code, changed.json()["detail"]) == (409, "id_conflict")
    assert (elsewhere.status_code, elsewhere.json()["detail"]) == (409, "id_conflict")


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        ({"id": str(uuid4()), "email": "a@example.test", "roles": ["analyst"]}, "id_not_uuid7"),
        ({"email": "sin-arroba", "roles": ["analyst"]}, "invalid_email"),
    ],
)
async def test_invalid_invitations_are_rejected(
    app: FastAPI, admin: Member, body: dict[str, Any], detail: str
) -> None:
    async with signed_in(app, admin.email) as client:
        response = await _post(client, "/api/app/invitations", {"id": str(_client_id()), **body})

    assert (response.status_code, response.json()["detail"]) == (422, detail)


async def test_inviting_needs_roles_and_an_admin(
    app: FastAPI, admin: Member, owner_engine: AsyncEngine
) -> None:
    analyst = await add_member(owner_engine, NOW, admin.organization_ids[0], ["analyst"])
    async with signed_in(app, admin.email) as client:
        no_roles = await _invite(client, "a@example.test", [])
        member = await _invite(client, analyst.email, ["reviewer"])
    async with signed_in(app, analyst.email) as client:
        forbidden = await _invite(client, "a@example.test", ["analyst"])
        team = await client.get("/api/app/team")

    assert no_roles.status_code == 422
    assert (member.status_code, member.json()["detail"]) == (409, "already_member")
    assert (forbidden.status_code, forbidden.json()["detail"]) == (403, "role_required")
    assert team.status_code == 403


async def test_an_invitation_that_cannot_be_used_gives_one_answer(
    app: FastAPI, admin: Member, owner_engine: AsyncEngine, clock: FixedClock
) -> None:
    existing = await add_member(owner_engine, NOW, admin.organization_ids[0], ["analyst"])
    outsider = await create_member(owner_engine, NOW, organizations={"Beta": ["analyst"]})
    email = f"nueva-{uuid7()}@example.test"
    async with signed_in(app, admin.email) as client:
        token = (await _invite(client, email, ["analyst"])).json()["token"]
        revoked = (await _invite(client, f"r-{email}", ["analyst"])).json()
        await _post(client, f"/api/app/invitations/{revoked['invitation']['id']}/revoke")
        for_outsider = (await _invite(client, outsider.email, ["analyst"])).json()["token"]
        late = (await _invite(client, f"late-{email}", ["analyst"])).json()["token"]

    wrong_email = await _new_account(app, token, f"otra-{email}")
    taken = await _new_account(app, for_outsider, outsider.email)
    revoked_answer = await _new_account(app, revoked["token"], f"r-{email}")
    used = await _new_account(app, token, email)
    again = await _new_account(app, token, email)
    clock.advance(timedelta(days=7))
    expired = await _new_account(app, late, f"late-{email}")

    assert used.status_code == 200
    for response in (wrong_email, taken, revoked_answer, again, expired):
        assert (response.status_code, response.json()["detail"]) == (409, "invitation_not_valid")
    async with owner_engine.connect() as connection:
        created = await connection.scalar(
            text("SELECT count(*) FROM users WHERE lower(email) = :email"),
            {"email": f"otra-{email}"},
        )
    assert created == 0
    assert existing.email != email


async def test_a_short_password_is_rejected(app: FastAPI, admin: Member) -> None:
    email = f"nueva-{uuid7()}@example.test"
    async with signed_in(app, admin.email) as client:
        token = (await _invite(client, email, ["analyst"])).json()["token"]
    async with signed_in(app) as visitor:
        response = await visitor.post(
            "/api/public/invitations/accept",
            json={"token": token, "email": email, "display_name": "N", "password": "corta"},
        )

    assert (response.status_code, response.json()["detail"]) == (422, "password_too_short")


async def test_an_existing_user_accepts_after_signing_in(
    app: FastAPI, admin: Member, owner_engine: AsyncEngine
) -> None:
    outsider = await create_member(owner_engine, NOW, organizations={"Beta": ["analyst"]})
    async with signed_in(app, admin.email) as client:
        token = (await _invite(client, outsider.email, ["reviewer"])).json()["token"]
    async with signed_in(app, outsider.email) as client:
        accepted = await _post(client, "/api/app/invitations/accept", {"token": token})
        reused = await _post(client, "/api/app/invitations/accept", {"token": token})
        organizations = (await client.get("/api/app/session")).json()["organizations"]

    assert accepted.json() == {"organization_id": str(admin.organization_ids[0])}
    assert (reused.status_code, reused.json()["detail"]) == (409, "invitation_not_valid")
    assert {o["name"]: o["roles"] for o in organizations} == {
        "Andina": ["reviewer"],
        "Beta": ["analyst"],
    }


async def test_revoking_hides_the_invitation_and_stays_within_the_organization(
    app: FastAPI, admin: Member, owner_engine: AsyncEngine
) -> None:
    other = await create_member(owner_engine, NOW, organizations={"Beta": ["admin"]})
    async with signed_in(app, admin.email) as client:
        invitation_id = (await _invite(client, "a@example.test", ["analyst"])).json()["invitation"][
            "id"
        ]
        async with signed_in(app, other.email) as stranger:
            foreign = await _post(stranger, f"/api/app/invitations/{invitation_id}/revoke")
            stranger_team = (await stranger.get("/api/app/team")).json()
        first = await _post(client, f"/api/app/invitations/{invitation_id}/revoke")
        second = await _post(client, f"/api/app/invitations/{invitation_id}/revoke")
        team = (await client.get("/api/app/team")).json()

    assert (foreign.status_code, foreign.json()["detail"]) == (404, "not_found")
    assert stranger_team["invitations"] == []
    assert [m["email"] for m in stranger_team["members"]] == [other.email]
    assert (first.status_code, second.status_code) == (204, 204)
    assert team["invitations"] == []
    actions = [action for action, _ in await _actions(owner_engine, admin.organization_ids[0])]
    assert actions.count("invitation.revoked") == 1


async def test_an_accepted_invitation_cannot_be_revoked(app: FastAPI, admin: Member) -> None:
    email = f"nueva-{uuid7()}@example.test"
    async with signed_in(app, admin.email) as client:
        created = (await _invite(client, email, ["analyst"])).json()
        await _new_account(app, created["token"], email)
        response = await _post(client, f"/api/app/invitations/{created['invitation']['id']}/revoke")

    assert (response.status_code, response.json()["detail"]) == (409, "invitation_accepted")


async def test_changing_roles_keeps_an_admin(
    app: FastAPI, admin: Member, owner_engine: AsyncEngine
) -> None:
    organization_id = admin.organization_ids[0]
    analyst = await add_member(owner_engine, NOW, organization_id, ["analyst"])
    stranger = await create_member(owner_engine, NOW, organizations={"Beta": ["analyst"]})
    async with signed_in(app, admin.email) as client:
        changed = await client.put(
            f"/api/app/team/members/{analyst.user_id}/roles",
            json={"roles": ["analyst", "reviewer"]},
            headers=xsrf_header(client),
        )
        demoted = await client.put(
            f"/api/app/team/members/{admin.user_id}/roles",
            json={"roles": ["analyst"]},
            headers=xsrf_header(client),
        )
        foreign = await client.put(
            f"/api/app/team/members/{stranger.user_id}/roles",
            json={"roles": ["analyst"]},
            headers=xsrf_header(client),
        )
        team = (await client.get("/api/app/team")).json()
    async with signed_in(app, analyst.email) as client:
        forbidden = await client.put(
            f"/api/app/team/members/{analyst.user_id}/roles",
            json={"roles": ["admin"]},
            headers=xsrf_header(client),
        )

    assert changed.status_code == 204
    assert (demoted.status_code, demoted.json()["detail"]) == (409, "last_admin")
    assert (foreign.status_code, foreign.json()["detail"]) == (404, "not_found")
    assert (forbidden.status_code, forbidden.json()["detail"]) == (403, "role_required")
    roles = {m["email"]: m["roles"] for m in team["members"]}
    assert roles[analyst.email] == ["analyst", "reviewer"]
    assert ("member.roles_changed", {"roles": ["analyst", "reviewer"]}) in await _actions(
        owner_engine, organization_id
    )


async def test_removing_a_member_ends_their_sessions_and_they_return_only_by_invitation(
    app: FastAPI, admin: Member, owner_engine: AsyncEngine
) -> None:
    organization_id = admin.organization_ids[0]
    analyst = await add_member(owner_engine, NOW, organization_id, ["admin", "analyst"])
    stranger = await create_member(owner_engine, NOW, organizations={"Beta": ["analyst"]})
    async with signed_in(app, admin.email) as client, signed_in(app, analyst.email) as removed:
        foreign = await _post(client, f"/api/app/team/members/{stranger.user_id}/remove")
        response = await _post(client, f"/api/app/team/members/{analyst.user_id}/remove")
        after = await removed.get("/api/app/session")
        last = await _post(client, f"/api/app/team/members/{admin.user_id}/remove")
        team = (await client.get("/api/app/team")).json()
        token = (await _invite(client, analyst.email, ["reviewer"])).json()["token"]
    async with signed_in(app, analyst.email) as client:
        await _post(client, "/api/app/invitations/accept", {"token": token})
        organizations = (await client.get("/api/app/session")).json()["organizations"]

    assert (foreign.status_code, foreign.json()["detail"]) == (404, "not_found")
    assert response.status_code == 204
    assert after.status_code == 401
    assert (last.status_code, last.json()["detail"]) == (409, "last_admin")
    assert [m["email"] for m in team["members"]] == [admin.email]
    assert [o["roles"] for o in organizations] == [["reviewer"]]
    actions = [action for action, _ in await _actions(owner_engine, organization_id)]
    assert "member.removed" in actions


async def test_two_admins_demoting_each_other_at_once_leave_one_admin(
    app: FastAPI, admin: Member, owner_engine: AsyncEngine
) -> None:
    organization_id = admin.organization_ids[0]
    second = await add_member(owner_engine, NOW, organization_id, ["admin"])
    async with signed_in(app, admin.email) as first, signed_in(app, second.email) as other:
        responses = await asyncio.gather(
            first.put(
                f"/api/app/team/members/{second.user_id}/roles",
                json={"roles": ["analyst"]},
                headers=xsrf_header(first),
            ),
            other.put(
                f"/api/app/team/members/{admin.user_id}/roles",
                json={"roles": ["analyst"]},
                headers=xsrf_header(other),
            ),
        )

    statuses = sorted(response.status_code for response in responses)
    assert statuses[0] == 204
    assert statuses[1] in {403, 409}
    assert await _admins(owner_engine, organization_id) == 1
