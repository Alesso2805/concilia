from alembic import op

revision = "0018"
down_revision = "0017"

TENANT = "NULLIF(current_setting('app.org_id', true), '')::uuid"

STATEMENTS = [
    """
    CREATE TABLE ai_suggestion_decisions (
        id uuid PRIMARY KEY,
        seq bigint GENERATED ALWAYS AS IDENTITY,
        organization_id uuid NOT NULL REFERENCES organizations (id),
        ai_suggestion_id uuid NOT NULL,
        suggestion_index integer NOT NULL CHECK (suggestion_index BETWEEN 0 AND 2),
        action text NOT NULL CHECK (action IN ('accept', 'reject')),
        reason text CHECK (length(reason) BETWEEN 1 AND 500),
        match_id uuid,
        decided_by uuid NOT NULL,
        decided_at timestamptz NOT NULL,
        UNIQUE (organization_id, id),
        UNIQUE (ai_suggestion_id, suggestion_index),
        FOREIGN KEY (organization_id, ai_suggestion_id)
            REFERENCES ai_suggestions (organization_id, id),
        FOREIGN KEY (organization_id, match_id) REFERENCES matches (organization_id, id),
        FOREIGN KEY (organization_id, decided_by)
            REFERENCES memberships (organization_id, user_id),
        CHECK ((action = 'accept') = (match_id IS NOT NULL)),
        CHECK (action = 'accept' OR reason IS NOT NULL)
    )
    """,
    "ALTER TABLE ai_suggestion_decisions ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE ai_suggestion_decisions FORCE ROW LEVEL SECURITY",
    f"""
    CREATE POLICY organization_isolation ON ai_suggestion_decisions
        USING (organization_id = {TENANT}) WITH CHECK (organization_id = {TENANT})
    """,
    "GRANT SELECT, INSERT ON ai_suggestion_decisions TO concilia_app, concilia_worker",
    """
    ALTER TABLE matches ADD CONSTRAINT matches_ai_suggestion_fkey
        FOREIGN KEY (organization_id, ai_suggestion_id)
        REFERENCES ai_suggestions (organization_id, id)
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
        DELETE FROM ai_suggestion_decisions WHERE organization_id = p_org_id;
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
