from collections.abc import AsyncIterator, Iterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from concilia.shared.infrastructure.db import create_engine
from tests.support.database import DatabaseUrls, running_database


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
def database() -> Iterator[DatabaseUrls]:
    with running_database() as urls:
        yield urls


async def _engine(database: DatabaseUrls, role: str) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(database.for_role(role))
    yield engine
    await engine.dispose()


@pytest.fixture
async def owner_engine(database: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    async for engine in _engine(database, "concilia_owner"):
        yield engine


@pytest.fixture
async def app_engine(database: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    async for engine in _engine(database, "concilia_app"):
        yield engine


@pytest.fixture
async def worker_engine(database: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    async for engine in _engine(database, "concilia_worker"):
        yield engine
