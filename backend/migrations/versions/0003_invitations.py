from alembic import op

revision = "0003"
down_revision = "0002"

TENANT = "NULLIF(current_setting('app.org_id', true), '')::uuid"
ACCEPT_INVITATION = "app_accept_invitation(text, uuid, timestamptz, uuid)"

STATEMENTS = [
    """
    CREATE TABLE invitations (
        id uuid PRIMARY KEY,
        organization_id uuid NOT NULL REFERENCES organizations (id),
        email text NOT NULL CHECK (email = lower(email)),
        roles text[] NOT NULL CHECK (
            cardinality(roles) > 0 AND roles <@ ARRAY['admin', 'analyst', 'reviewer']
        ),
        token_hash text NOT NULL UNIQUE,
        created_by uuid NOT NULL,
        created_at timestamptz NOT NULL,
        expires_at timestamptz NOT NULL,
        accepted_at timestamptz,
        revoked_at timestamptz,
        UNIQUE (organization_id, id),
        FOREIGN KEY (organization_id, created_by) REFERENCES memberships (organization_id, user_id),
        CHECK (expires_at > created_at),
        CHECK (accepted_at IS NULL OR revoked_at IS NULL)
    )
    """,
    "CREATE INDEX invitations_listing_idx ON invitations (organization_id, created_at)",
    "ALTER TABLE invitations ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE invitations FORCE ROW LEVEL SECURITY",
    f"""
    CREATE POLICY organization_isolation ON invitations
        USING (organization_id = {TENANT}) WITH CHECK (organization_id = {TENANT})
    """,
    "GRANT SELECT, INSERT ON invitations TO concilia_app, concilia_worker",
    "GRANT UPDATE (revoked_at) ON invitations TO concilia_app, concilia_worker",
    """
    CREATE FUNCTION app_accept_invitation(
        p_token_hash text, p_user_id uuid, p_now timestamptz, p_event_id uuid
    )
        RETURNS uuid
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public
    AS $$
    DECLARE
        v_invitation invitations%ROWTYPE;
    BEGIN
        SELECT * INTO v_invitation FROM invitations WHERE token_hash = p_token_hash;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'invitation_not_valid';
        END IF;
        PERFORM pg_advisory_xact_lock(1, hashtext(v_invitation.organization_id::text));
        SELECT * INTO v_invitation FROM invitations WHERE id = v_invitation.id FOR UPDATE;
        IF v_invitation.accepted_at IS NOT NULL
            OR v_invitation.revoked_at IS NOT NULL
            OR v_invitation.expires_at <= p_now
            OR NOT EXISTS (
                SELECT 1 FROM users WHERE id = p_user_id AND lower(email) = v_invitation.email
            )
            OR EXISTS (
                SELECT 1 FROM memberships
                WHERE organization_id = v_invitation.organization_id
                  AND user_id = p_user_id AND removed_at IS NULL
            )
        THEN
            RAISE EXCEPTION 'invitation_not_valid';
        END IF;

        INSERT INTO memberships (organization_id, user_id, created_at)
        VALUES (v_invitation.organization_id, p_user_id, p_now)
        ON CONFLICT (organization_id, user_id) DO UPDATE SET removed_at = NULL;
        DELETE FROM member_roles
        WHERE organization_id = v_invitation.organization_id AND user_id = p_user_id;
        INSERT INTO member_roles (organization_id, user_id, role)
        SELECT v_invitation.organization_id, p_user_id, unnest(v_invitation.roles);
        UPDATE invitations SET accepted_at = p_now WHERE id = v_invitation.id;
        INSERT INTO audit_events (id, organization_id, actor_user_id, action, entity, entity_id,
                                  metadata, at)
        VALUES (p_event_id, v_invitation.organization_id, p_user_id, 'invitation.accepted',
                'invitation', v_invitation.id,
                jsonb_build_object('roles', to_jsonb(v_invitation.roles)), p_now);
        RETURN v_invitation.organization_id;
    END
    $$
    """,
    f"REVOKE ALL ON FUNCTION {ACCEPT_INVITATION} FROM PUBLIC",
    f"GRANT EXECUTE ON FUNCTION {ACCEPT_INVITATION} TO concilia_app",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
