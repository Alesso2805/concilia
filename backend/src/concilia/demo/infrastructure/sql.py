from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from concilia.demo.application.creation import DemoStores
from concilia.shared.infrastructure.db import organization_transaction


class SqlDemoTransactions:
    """Creates a demo in one transaction whose `app.org_id` is the new organization, with the
    stores of every module on that connection (built by the composition root)."""

    def __init__(
        self, engine: AsyncEngine, stores: Callable[[AsyncConnection], DemoStores]
    ) -> None:
        self._engine = engine
        self._stores = stores

    @asynccontextmanager
    async def organization(self, organization_id: UUID) -> AsyncIterator[DemoStores]:
        async with organization_transaction(self._engine, organization_id) as connection:
            yield self._stores(connection)


class SqlDemoQueries:
    def __init__(self, connection: AsyncConnection) -> None:
        self._connection = connection

    async def is_demo(self, organization_id: UUID) -> bool:
        found = await self._connection.scalar(
            text("SELECT is_demo FROM organizations WHERE id = :id"), {"id": organization_id}
        )
        return bool(found)


class SqlDemoReadTransactions:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @asynccontextmanager
    async def organization(self, organization_id: UUID) -> AsyncIterator[SqlDemoQueries]:
        async with organization_transaction(self._engine, organization_id) as connection:
            yield SqlDemoQueries(connection)
