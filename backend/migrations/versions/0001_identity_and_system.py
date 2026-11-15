from alembic import op

revision = "0001"
down_revision = None

TENANT = "NULLIF(current_setting('app.org_id', true), '')::uuid"

STATEMENTS = [
    "ALTER DEFAULT PRIVILEGES FOR ROLE concilia_owner REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC",
    "ALTER DEFAULT PRIVILEGES FOR ROLE concilia_owner GRANT SELECT ON TABLES TO concilia_backup",
    "ALTER DEFAULT PRIVILEGES FOR ROLE concilia_owner GRANT SELECT ON SEQUENCES TO concilia_backup",
    """
    CREATE TABLE users (
        id uuid PRIMARY KEY,
        email text NOT NULL,
        password_hash text,
        display_name text NOT NULL,
        is_demo boolean NOT NULL DEFAULT false,
        created_at timestamptz NOT NULL,
        CHECK (NOT is_demo OR password_hash IS NULL)
    )
    """,
    "CREATE UNIQUE INDEX users_email_key ON users (lower(email))",
    """
    CREATE TABLE organizations (
        id uuid PRIMARY KEY,
        name text NOT NULL,
        tolerance_min_cents bigint NOT NULL DEFAULT 100 CHECK (tolerance_min_cents >= 0),
        tolerance_bp integer NOT NULL DEFAULT 50 CHECK (tolerance_bp BETWEEN 0 AND 10000),
        detraction_rates_bp integer[] NOT NULL DEFAULT '{1000,1200}',
        is_demo boolean NOT NULL DEFAULT false,
        demo_expires_at timestamptz,
        created_at timestamptz NOT NULL,
        CHECK (is_demo = (demo_expires_at IS NOT NULL))
    )
    """,
    """
    CREATE TABLE memberships (
        organization_id uuid NOT NULL REFERENCES organizations (id),
        user_id uuid NOT NULL REFERENCES users (id),
        created_at timestamptz NOT NULL,
        removed_at timestamptz,
        PRIMARY KEY (organization_id, user_id)
    )
    """,
    "CREATE INDEX memberships_user_id_idx ON memberships (user_id)",
    """
    CREATE TABLE member_roles (
        organization_id uuid NOT NULL,
        user_id uuid NOT NULL,
        role text NOT NULL CHECK (role IN ('admin', 'analyst', 'reviewer')),
        PRIMARY KEY (organization_id, user_id, role),
        FOREIGN KEY (organization_id, user_id) REFERENCES memberships (organization_id, user_id)
    )
    """,
    """
    CREATE TABLE sessions (
        id uuid PRIMARY KEY,
        user_id uuid NOT NULL REFERENCES users (id),
        organization_id uuid REFERENCES organizations (id),
        token_hash text NOT NULL UNIQUE,
        created_at timestamptz NOT NULL,
        last_seen_at timestamptz NOT NULL,
        expires_at timestamptz NOT NULL,
        revoked_at timestamptz
    )
    """,
    "CREATE INDEX sessions_user_id_idx ON sessions (user_id)",
    """
    CREATE UNLOGGED TABLE rate_limits (
        key_hash text NOT NULL,
        window_start timestamptz NOT NULL,
        count integer NOT NULL CHECK (count >= 0),
        PRIMARY KEY (key_hash, window_start)
    )
    """,
    """
    CREATE TABLE audit_events (
        id uuid PRIMARY KEY,
        seq bigint GENERATED ALWAYS AS IDENTITY,
        organization_id uuid NOT NULL REFERENCES organizations (id),
        actor_user_id uuid,
        action text NOT NULL,
        entity text NOT NULL,
        entity_id uuid,
        metadata jsonb NOT NULL DEFAULT '{}',
        at timestamptz NOT NULL,
        UNIQUE (organization_id, id),
        FOREIGN KEY (organization_id, actor_user_id)
            REFERENCES memberships (organization_id, user_id)
    )
    """,
    "CREATE INDEX audit_events_organization_seq_idx ON audit_events (organization_id, seq)",
    """
    CREATE TABLE jobs (
        id uuid PRIMARY KEY,
        organization_id uuid REFERENCES organizations (id),
        kind text NOT NULL CHECK (kind IN ('noop', 'parse_import', 'confirm_import', 'run_engine',
                                           'ai_suggest', 'export_period', 'cleanup')),
        payload jsonb NOT NULL DEFAULT '{}',
        status text NOT NULL DEFAULT 'queued'
            CHECK (status IN ('queued', 'running', 'done', 'failed')),
        progress integer NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
        attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
        run_after timestamptz NOT NULL,
        locked_at timestamptz,
        dedup_key text,
        error_code text,
        created_by uuid,
        created_at timestamptz NOT NULL,
        finished_at timestamptz,
        UNIQUE (organization_id, id),
        CHECK (organization_id IS NOT NULL OR kind IN ('noop', 'cleanup')),
        FOREIGN KEY (organization_id, created_by) REFERENCES memberships (organization_id, user_id)
    )
    """,
    """
    CREATE UNIQUE INDEX jobs_active_dedup_key ON jobs (kind, dedup_key)
        WHERE status IN ('queued', 'running')
    """,
    "CREATE INDEX jobs_claim_idx ON jobs (run_after, id) WHERE status = 'queued'",
    "CREATE INDEX jobs_running_idx ON jobs (locked_at) WHERE status = 'running'",
    "CREATE INDEX jobs_organization_idx ON jobs (organization_id, created_at)",
    *[
        statement
        for table in ("organizations", "memberships", "member_roles", "audit_events", "jobs")
        for statement in (
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        )
    ],
    f"""
    CREATE POLICY organization_isolation ON organizations
        USING (id = {TENANT}) WITH CHECK (id = {TENANT})
    """,
    *[
        f"""
        CREATE POLICY organization_isolation ON {table}
            USING (organization_id = {TENANT}) WITH CHECK (organization_id = {TENANT})
        """
        for table in ("memberships", "member_roles", "audit_events")
    ],
    f"""
    CREATE POLICY jobs_of_organization ON jobs TO concilia_app
        USING (organization_id = {TENANT}) WITH CHECK (organization_id = {TENANT})
    """,
    """
    CREATE POLICY jobs_of_every_organization ON jobs TO concilia_worker
        USING (true) WITH CHECK (true)
    """,
    """
    GRANT SELECT, INSERT ON organizations, memberships, member_roles, audit_events, jobs
        TO concilia_app, concilia_worker
    """,
    """
    GRANT UPDATE (name, tolerance_min_cents, tolerance_bp, detraction_rates_bp) ON organizations
        TO concilia_app, concilia_worker
    """,
    "GRANT UPDATE (removed_at) ON memberships TO concilia_app, concilia_worker",
    "GRANT DELETE ON member_roles TO concilia_app, concilia_worker",
    """
    GRANT UPDATE (status, progress, attempts, run_after, locked_at, error_code, finished_at)
        ON jobs TO concilia_worker
    """,
    "GRANT SELECT, INSERT ON users TO concilia_app",
    "GRANT UPDATE (password_hash, display_name) ON users TO concilia_app",
    "GRANT SELECT (id, display_name) ON users TO concilia_worker",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON sessions, rate_limits TO concilia_app",
    """
    CREATE FUNCTION app_cleanup(p_now timestamptz) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public
    AS $$
    BEGIN
        PERFORM p_now;
    END
    $$
    """,
    "REVOKE ALL ON FUNCTION app_cleanup(timestamptz) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION app_cleanup(timestamptz) TO concilia_worker",
    "GRANT SELECT ON ALL TABLES IN SCHEMA public TO concilia_backup",
    "GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO concilia_backup",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
