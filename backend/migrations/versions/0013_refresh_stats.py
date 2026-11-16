from alembic import op

revision = "0013"
down_revision = "0012"

# Right after a bulk load (a new demo, a confirmed import) the planner's statistics do not know
# the new rows yet and estimate about one row per organization, which turns organization-wide
# reads quadratic until autovacuum analyzes the tables. The application runs this after such
# loads; it only analyzes this fixed list of tables.
STATEMENTS = [
    """
    CREATE FUNCTION app_refresh_stats() RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public
    AS $$
    BEGIN
        ANALYZE bank_movements, receivables, matches, match_items, match_decisions;
    END
    $$
    """,
    "REVOKE ALL ON FUNCTION app_refresh_stats() FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION app_refresh_stats() TO concilia_app, concilia_worker",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
