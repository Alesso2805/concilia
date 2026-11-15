import httpx
import pytest

from concilia.api import create_app

pytestmark = pytest.mark.anyio


async def test_health_reports_ok() -> None:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
