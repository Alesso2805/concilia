import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.architecture.catalog import catalog_violations, load_expected

pytestmark = pytest.mark.anyio


async def test_catalog_matches_db_grants(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as connection:
        assert await catalog_violations(connection, load_expected()) == []


@pytest.mark.parametrize(
    "ddl",
    [
        "CREATE TABLE rogue (id uuid PRIMARY KEY, organization_id uuid NOT NULL)",
        "ALTER TABLE memberships NO FORCE ROW LEVEL SECURITY",
        "CREATE VIEW rogue_view AS SELECT id FROM organizations",
        "GRANT UPDATE ON organizations TO concilia_app",
        "GRANT SELECT (email) ON users TO concilia_worker",
        "GRANT DELETE ON audit_events TO PUBLIC",
        "GRANT EXECUTE ON FUNCTION app_cleanup(timestamptz) TO concilia_app",
        "CREATE POLICY open_door ON audit_events FOR SELECT USING (true)",
        "CREATE FUNCTION rogue() RETURNS int LANGUAGE sql SECURITY DEFINER AS 'SELECT 1'",
    ],
)
async def test_catalog_detects_violation(owner_engine: AsyncEngine, ddl: str) -> None:
    async with owner_engine.connect() as connection:
        await connection.execute(text(ddl))
        violations = await catalog_violations(connection, load_expected())
        await connection.rollback()

    assert violations != []
