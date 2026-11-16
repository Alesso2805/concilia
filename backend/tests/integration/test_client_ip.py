import httpx
import pytest
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from tests.support.api import ORIGIN, build_app
from tests.support.clock import FixedClock
from tests.support.database import DatabaseUrls
from tests.support.imports import NOW

pytestmark = pytest.mark.anyio

CADDY = "10.89.47.10"


async def test_the_client_ip_comes_from_caddy_and_cannot_be_forged_around_it(
    database: DatabaseUrls,
) -> None:
    """The same middleware and trusted address Uvicorn runs with in compose (`--proxy-headers`,
    `FORWARDED_ALLOW_IPS`): per-IP limits see the visitor's address only when Caddy sends it."""
    app = build_app(
        database.for_role("concilia_app"),
        FixedClock(NOW),
        demo_max_per_ip_per_day=1,
    )
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=CADDY)

    async def create_demo(peer: str, forwarded_for: str) -> int:
        transport = httpx.ASGITransport(app=app, client=(peer, 50_000))
        async with httpx.AsyncClient(
            transport=transport,
            base_url=ORIGIN,
            headers={"Origin": ORIGIN, "X-Forwarded-For": forwarded_for},
        ) as client:
            return (await client.post("/api/public/demo")).status_code

    try:
        first_visitor = await create_demo(CADDY, "198.51.100.21")
        second_visitor = await create_demo(CADDY, "198.51.100.22")
        first_again = await create_demo(CADDY, "198.51.100.21")
        forged_elsewhere = await create_demo("198.51.100.23", "198.51.100.22")
    finally:
        await app.state.engine.dispose()

    assert (first_visitor, second_visitor, first_again) == (201, 201, 429)
    assert forged_elsewhere == 201
