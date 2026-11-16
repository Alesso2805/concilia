from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

REFRESHED = ("bank_movements", "receivables", "matches", "match_items", "match_decisions")


async def manual_analyze_counts(owner_engine: AsyncEngine) -> dict[str, int]:
    async with owner_engine.connect() as connection:
        rows = await connection.execute(
            text(
                """SELECT relname, analyze_count FROM pg_stat_user_tables
                   WHERE relname = ANY(:tables)"""
            ),
            {"tables": list(REFRESHED)},
        )
        return dict(rows.all())


def all_grew(before: dict[str, int], after: dict[str, int]) -> bool:
    return all(after[table] > before[table] for table in REFRESHED)
