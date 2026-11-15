from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from enum import IntEnum
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine


class LockNamespace(IntEnum):
    ORGANIZATION = 1
    JOB = 2
    AI_QUOTA = 3


def create_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, pool_pre_ping=True)


@asynccontextmanager
async def anonymous_transaction(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    async with engine.begin() as connection:
        yield connection


@asynccontextmanager
async def organization_transaction(
    engine: AsyncEngine, organization_id: UUID
) -> AsyncIterator[AsyncConnection]:
    async with engine.begin() as connection:
        await connection.execute(
            text("SELECT set_config('app.org_id', :organization_id, true)"),
            {"organization_id": str(organization_id)},
        )
        yield connection


async def lock_organization(connection: AsyncConnection, organization_id: UUID) -> None:
    await connection.execute(
        text("SELECT pg_advisory_xact_lock(:namespace, hashtext(:key))"),
        {"namespace": LockNamespace.ORGANIZATION.value, "key": str(organization_id)},
    )
