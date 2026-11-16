import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.architecture.catalog import catalog_violations, load_expected

pytestmark = pytest.mark.anyio


async def test_catalog_matches_db_grants(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as connection:
        assert await catalog_violations(connection, load_expected()) == []


@pytest.mark.parametrize(
    ("ddl", "expected"),
    [
        (
            "CREATE TABLE rogue (id uuid PRIMARY KEY, organization_id uuid NOT NULL)",
            "rogue is not declared",
        ),
        (
            "ALTER TABLE memberships NO FORCE ROW LEVEL SECURITY",
            "memberships has RLS=True FORCE=False",
        ),
        ("CREATE VIEW rogue_view AS SELECT id FROM organizations", "rogue_view is not declared"),
        (
            "ALTER VIEW period_status RESET (security_invoker)",
            "view period_status lacks security_invoker",
        ),
        (
            "GRANT UPDATE ON organizations TO concilia_app",
            "('organizations', 'concilia_app', 'UPDATE')",
        ),
        (
            "GRANT SELECT (email) ON users TO concilia_worker",
            "('users', 'email', 'concilia_worker'",
        ),
        ("GRANT DELETE ON audit_events TO PUBLIC", "('audit_events', 'PUBLIC', 'DELETE')"),
        (
            "GRANT EXECUTE ON FUNCTION app_cleanup(timestamptz) TO concilia_app",
            "function app_cleanup is executable by",
        ),
        (
            "CREATE POLICY open_door ON audit_events FOR SELECT USING (true)",
            "audit_events policies",
        ),
        (
            "CREATE FUNCTION rogue() RETURNS int LANGUAGE sql SECURITY DEFINER AS 'SELECT 1'",
            "function rogue is not declared",
        ),
    ],
)
async def test_catalog_detects_violation(
    owner_engine: AsyncEngine, ddl: str, expected: str
) -> None:
    async with owner_engine.connect() as connection:
        await connection.execute(text(ddl))
        violations = await catalog_violations(connection, load_expected())
        await connection.rollback()

    assert any(expected in violation for violation in violations), violations
