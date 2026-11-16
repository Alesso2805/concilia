from alembic import op

revision = "0014"
down_revision = "0013"

STATEMENTS = [
    """
    CREATE FUNCTION period_events_alternate() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
    DECLARE
        v_last text;
    BEGIN
        PERFORM pg_advisory_xact_lock(1, hashtext(NEW.organization_id::text));
        SELECT action INTO v_last FROM period_events
        WHERE organization_id = NEW.organization_id
          AND bank_account_id = NEW.bank_account_id
          AND period = NEW.period
        ORDER BY seq DESC LIMIT 1;
        IF NEW.action = 'close' AND v_last = 'close' THEN
            RAISE EXCEPTION 'period_already_closed' USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.action = 'reopen' AND v_last IS DISTINCT FROM 'close' THEN
            RAISE EXCEPTION 'period_not_closed' USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END
    $$
    """,
    """
    CREATE TRIGGER period_events_alternate BEFORE INSERT ON period_events
        FOR EACH ROW EXECUTE FUNCTION period_events_alternate()
    """,
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
