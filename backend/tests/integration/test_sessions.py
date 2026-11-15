from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.support.api import PASSWORD, api_client, build_app, create_member, xsrf_header
from tests.support.clock import FixedClock
from tests.support.database import DatabaseUrls

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 11, 23, 14, 0, tzinfo=UTC)
CUSTOMER_TEXT = "ACME SAC PAGO F001-123"


@pytest.fixture
def session_clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
async def client(
    database: DatabaseUrls, session_clock: FixedClock
) -> AsyncIterator[httpx.AsyncClient]:
    async with api_client(build_app(database.for_role("concilia_app"), session_clock)) as client:
        yield client


async def _login(client: httpx.AsyncClient, email: str, password: str = PASSWORD) -> httpx.Response:
    return await client.post("/api/public/login", json={"email": email, "password": password})


async def test_login_with_one_organization_selects_it(
    client: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    member = await create_member(owner_engine, NOW, organizations={"Alfa": ["analyst", "reviewer"]})

    response = await _login(client, member.email.upper())

    assert response.status_code == 200
    assert response.json()["organization_id"] == str(member.organization_ids[0])
    cookie_header = ";".join(response.headers.get_list("set-cookie"))
    assert "__Host-concilia_session=" in cookie_header
    assert "HttpOnly" in cookie_header
    session = (await client.get("/api/app/session")).json()
    assert session["roles"] == ["analyst", "reviewer"]


@pytest.mark.parametrize("case", ["wrong_password", "unknown_email", "demo_user"])
async def test_failed_logins_look_the_same(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, case: str
) -> None:
    member = await create_member(
        owner_engine,
        NOW,
        organizations={"Alfa": ["admin"]},
        password=None if case == "demo_user" else PASSWORD,
    )
    email = "nobody@example.test" if case == "unknown_email" else member.email

    response = await _login(
        client, email, "wrong password" if case == "wrong_password" else PASSWORD
    )

    assert (response.status_code, response.json()) == (401, {"detail": "invalid_credentials"})


async def test_login_attempts_are_limited_per_email(
    client: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    member = await create_member(owner_engine, NOW, organizations={"Alfa": ["admin"]})
    for _ in range(10):
        await _login(client, member.email, "wrong password")

    response = await _login(client, member.email)

    assert response.status_code == 429
    assert 0 < int(response.headers["Retry-After"]) <= 15 * 60


async def test_public_routes_require_the_site_origin(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/public/login",
        json={"email": "a@example.test", "password": "x"},
        headers={"Origin": "https://evil.test"},
    )

    assert (response.status_code, response.json()) == (403, {"detail": "origin_not_allowed"})


async def test_unsafe_requests_need_the_csrf_token(
    client: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    member = await create_member(owner_engine, NOW, organizations={"Alfa": ["admin"]})
    await _login(client, member.email)

    without_token = await client.post("/api/app/logout")
    with_token = await client.post("/api/app/logout", headers=xsrf_header(client))

    assert (without_token.status_code, without_token.json()) == (403, {"detail": "csrf_failed"})
    assert with_token.status_code == 204
    assert (await client.get("/api/app/session")).status_code == 401


@pytest.mark.parametrize(
    ("idle_step", "steps", "expected"),
    [
        (timedelta(hours=11, minutes=59), 1, 200),
        (timedelta(hours=12), 1, 401),
        (timedelta(hours=11), 16, 401),
    ],
)
async def test_sessions_expire_when_idle_or_too_old(
    client: httpx.AsyncClient,
    owner_engine: AsyncEngine,
    session_clock: FixedClock,
    idle_step: timedelta,
    steps: int,
    expected: int,
) -> None:
    member = await create_member(owner_engine, NOW, organizations={"Alfa": ["admin"]})
    await _login(client, member.email)
    status_code = 200
    for _ in range(steps):
        session_clock.advance(idle_step)
        status_code = (await client.get("/api/app/session")).status_code

    assert status_code == expected


async def test_choosing_an_organization_rotates_the_session(
    client: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    member = await create_member(
        owner_engine, NOW, organizations={"Alfa": ["analyst"], "Beta": ["reviewer"]}
    )
    login = await _login(client, member.email)
    assert login.json()["organization_id"] is None
    old_token = client.cookies["__Host-concilia_session"]

    response = await client.post(
        "/api/app/session/organization",
        json={"organization_id": str(member.organization_ids[1])},
        headers=xsrf_header(client),
    )

    assert response.status_code == 200
    assert client.cookies["__Host-concilia_session"] != old_token
    assert (await client.get("/api/app/session")).json()["roles"] == ["reviewer"]
    client.cookies.set("__Host-concilia_session", old_token)
    assert (await client.get("/api/app/session")).status_code == 401


async def test_a_session_cannot_enter_another_users_organization(
    client: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    alpha = await create_member(owner_engine, NOW, organizations={"Alfa": ["admin"]})
    beta = await create_member(owner_engine, NOW, organizations={"Beta": ["admin"]})
    await _login(client, alpha.email)

    response = await client.post(
        "/api/app/session/organization",
        json={"organization_id": str(beta.organization_ids[0])},
        headers=xsrf_header(client),
    )
    session = (await client.get("/api/app/session")).json()

    assert (response.status_code, response.json()) == (403, {"detail": "not_a_member"})
    assert session["organization_id"] == str(alpha.organization_ids[0])
    assert [o["id"] for o in session["organizations"]] == [str(alpha.organization_ids[0])]


async def test_validation_errors_do_not_echo_the_request(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/public/login", json={"email": CUSTOMER_TEXT * 40, "password": CUSTOMER_TEXT}
    )

    assert response.status_code == 422
    assert "ACME" not in response.text
