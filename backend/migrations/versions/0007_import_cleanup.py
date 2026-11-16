from alembic import op

revision = "0007"
down_revision = "0006"

STATEMENTS = [
    """
    CREATE OR REPLACE FUNCTION app_cleanup(p_now timestamptz) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public
    AS $$
    BEGIN
        UPDATE import_files SET status = 'discarded', discarded_at = p_now
        WHERE status = 'previewed' AND created_at < p_now - interval '24 hours';
        UPDATE import_files SET status = 'failed', error_code = 'abandoned'
        WHERE status IN ('uploaded', 'parsing') AND created_at < p_now - interval '24 hours';
        DELETE FROM import_rows r
        USING import_files f
        WHERE r.import_file_id = f.id AND f.status IN ('discarded', 'failed');
    END
    $$
    """,
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
