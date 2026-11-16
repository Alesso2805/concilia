import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@pytest.fixture(autouse=True)
async def fresh_rate_limits(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as connection:
        await connection.execute(text("TRUNCATE rate_limits"))
