from alembic import op

revision = "0016"
down_revision = "0015"

TENANT = "NULLIF(current_setting('app.org_id', true), '')::uuid"

STATEMENTS = [
    """
    CREATE TABLE exports (
        id uuid PRIMARY KEY,
        organization_id uuid NOT NULL REFERENCES organizations (id),
        bank_account_id uuid NOT NULL,
        period date NOT NULL CHECK (period = date_trunc('month', period)::date),
        job_id uuid NOT NULL UNIQUE,
        content bytea NOT NULL,
        created_by uuid NOT NULL,
        created_at timestamptz NOT NULL,
        expires_at timestamptz NOT NULL,
        UNIQUE (organization_id, id),
        FOREIGN KEY (organization_id, bank_account_id)
            REFERENCES bank_accounts (organization_id, id),
        FOREIGN KEY (organization_id, created_by)
            REFERENCES memberships (organization_id, user_id),
        CHECK (expires_at > created_at)
    )
    """,
    "CREATE INDEX exports_expires_idx ON exports (expires_at)",
    "ALTER TABLE exports ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE exports FORCE ROW LEVEL SECURITY",
    f"""
    CREATE POLICY organization_isolation ON exports
        USING (organization_id = {TENANT}) WITH CHECK (organization_id = {TENANT})
    """,
    "GRANT SELECT, INSERT ON exports TO concilia_app, concilia_worker",
    """
    CREATE OR REPLACE FUNCTION app_reset_demo(p_org_id uuid) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public
    AS $$
    DECLARE
        v_users uuid[];
    BEGIN
        PERFORM pg_advisory_xact_lock(1, hashtext(p_org_id::text));
        IF NOT EXISTS (SELECT 1 FROM organizations WHERE id = p_org_id AND is_demo) THEN
            RETURN;
        END IF;
        v_users := ARRAY(
            SELECT m.user_id FROM memberships m JOIN users u ON u.id = m.user_id
            WHERE m.organization_id = p_org_id AND u.is_demo
        );
        DELETE FROM exports WHERE organization_id = p_org_id;
        DELETE FROM match_decisions WHERE organization_id = p_org_id;
        DELETE FROM match_items WHERE organization_id = p_org_id;
        DELETE FROM matches WHERE organization_id = p_org_id;
        DELETE FROM engine_runs WHERE organization_id = p_org_id;
        DELETE FROM period_events WHERE organization_id = p_org_id;
        DELETE FROM receivables WHERE organization_id = p_org_id;
        DELETE FROM bank_movements WHERE organization_id = p_org_id;
        DELETE FROM import_rows WHERE organization_id = p_org_id;
        DELETE FROM import_files WHERE organization_id = p_org_id;
        DELETE FROM import_profiles WHERE organization_id = p_org_id;
        DELETE FROM bank_accounts WHERE organization_id = p_org_id;
        DELETE FROM invitations WHERE organization_id = p_org_id;
        DELETE FROM audit_events WHERE organization_id = p_org_id;
        DELETE FROM jobs WHERE organization_id = p_org_id;
        DELETE FROM sessions WHERE organization_id = p_org_id OR user_id = ANY(v_users);
        DELETE FROM member_roles WHERE organization_id = p_org_id;
        DELETE FROM memberships WHERE organization_id = p_org_id;
        DELETE FROM users WHERE id = ANY(v_users);
        DELETE FROM organizations WHERE id = p_org_id;
    END
    $$
    """,
    """
    CREATE OR REPLACE FUNCTION app_cleanup(p_now timestamptz) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public
    AS $$
    DECLARE
        v_demo uuid;
    BEGIN
        UPDATE import_files SET status = 'discarded', discarded_at = p_now
        WHERE status = 'previewed' AND created_at < p_now - interval '24 hours';
        UPDATE import_files SET status = 'failed', error_code = 'abandoned'
        WHERE status IN ('uploaded', 'parsing') AND created_at < p_now - interval '24 hours';
        DELETE FROM import_rows r
        USING import_files f
        WHERE r.import_file_id = f.id AND f.status IN ('discarded', 'failed');
        DELETE FROM exports WHERE expires_at <= p_now;
        FOR v_demo IN
            SELECT id FROM organizations WHERE is_demo AND demo_expires_at <= p_now ORDER BY id
        LOOP
            PERFORM app_reset_demo(v_demo);
        END LOOP;
    END
    $$
    """,
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
