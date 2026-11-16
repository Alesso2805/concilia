from alembic import op

revision = "0017"
down_revision = "0016"

TENANT = "NULLIF(current_setting('app.org_id', true), '')::uuid"

STATEMENTS = [
    """
    CREATE TABLE ai_suggestions (
        id uuid PRIMARY KEY,
        organization_id uuid NOT NULL REFERENCES organizations (id),
        job_id uuid NOT NULL UNIQUE,
        bank_movement_id uuid NOT NULL,
        model text NOT NULL CHECK (length(model) BETWEEN 1 AND 100),
        prompt_version integer NOT NULL CHECK (prompt_version > 0),
        candidates jsonb NOT NULL CHECK (jsonb_typeof(candidates) = 'object'),
        response jsonb NOT NULL,
        server_applied jsonb CHECK (jsonb_typeof(server_applied) = 'array'),
        valid boolean NOT NULL,
        replayed boolean NOT NULL,
        input_tokens integer NOT NULL CHECK (input_tokens >= 0),
        output_tokens integer NOT NULL CHECK (output_tokens >= 0),
        created_by uuid NOT NULL,
        created_at timestamptz NOT NULL,
        UNIQUE (organization_id, id),
        FOREIGN KEY (organization_id, bank_movement_id)
            REFERENCES bank_movements (organization_id, id),
        FOREIGN KEY (organization_id, created_by)
            REFERENCES memberships (organization_id, user_id),
        CHECK (valid = (server_applied IS NOT NULL))
    )
    """,
    "CREATE INDEX ai_suggestions_movement_idx ON ai_suggestions (bank_movement_id)",
    "ALTER TABLE ai_suggestions ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE ai_suggestions FORCE ROW LEVEL SECURITY",
    f"""
    CREATE POLICY organization_isolation ON ai_suggestions
        USING (organization_id = {TENANT}) WITH CHECK (organization_id = {TENANT})
    """,
    "GRANT SELECT, INSERT ON ai_suggestions TO concilia_app, concilia_worker",
    """
    CREATE FUNCTION app_ai_usage_today(p_from timestamptz, p_to timestamptz) RETURNS bigint
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
    AS $$
        SELECT count(*) FROM jobs j JOIN organizations o ON o.id = j.organization_id
        WHERE j.kind = 'ai_suggest' AND NOT o.is_demo
          AND j.created_at >= p_from AND j.created_at < p_to
    $$
    """,
    "REVOKE ALL ON FUNCTION app_ai_usage_today(timestamptz, timestamptz) FROM PUBLIC",
    """
    GRANT EXECUTE ON FUNCTION app_ai_usage_today(timestamptz, timestamptz)
        TO concilia_app, concilia_worker
    """,
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
        DELETE FROM ai_suggestions WHERE organization_id = p_org_id;
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
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
