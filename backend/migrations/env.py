import asyncio
import os

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine


def _run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()


async def _migrate(url: str) -> None:
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        await connection.run_sync(_run_migrations)
        await connection.commit()
    await engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("offline migrations are not supported")

asyncio.run(
    _migrate(context.config.attributes.get("url") or os.environ["CONCILIA_MIGRATIONS_DATABASE_URL"])
)
