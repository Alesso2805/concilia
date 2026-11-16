from datetime import UTC, datetime

import pytest

from tests.support.api import api_client, build_app
from tests.support.clock import FixedClock
from tests.support.database import DatabaseUrls

pytestmark = pytest.mark.anyio


async def test_health_reports_ok(database: DatabaseUrls) -> None:
    clock = FixedClock(datetime(2026, 11, 23, tzinfo=UTC))
    async with api_client(build_app(database.for_role("concilia_app"), clock)) as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_reports_an_unreachable_database() -> None:
    clock = FixedClock(datetime(2026, 11, 23, tzinfo=UTC))
    app = build_app("postgresql+asyncpg://concilia_app:x@127.0.0.1:1/concilia", clock)
    async with api_client(app) as client:
        response = await client.get("/api/health")

    assert (response.status_code, response.json()["detail"]) == (503, "database_unavailable")
