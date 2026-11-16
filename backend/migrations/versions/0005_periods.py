from alembic import op

revision = "0005"
down_revision = "0004"

TENANT = "NULLIF(current_setting('app.org_id', true), '')::uuid"

STATEMENTS = [
    """
    CREATE TABLE period_events (
        id uuid PRIMARY KEY,
        seq bigint GENERATED ALWAYS AS IDENTITY,
        organization_id uuid NOT NULL REFERENCES organizations (id),
        bank_account_id uuid NOT NULL,
        period date NOT NULL CHECK (period = date_trunc('month', period)::date),
        action text NOT NULL CHECK (action IN ('close', 'reopen')),
        reason text CHECK (length(reason) BETWEEN 1 AND 500),
        decided_by uuid NOT NULL,
        decided_at timestamptz NOT NULL,
        UNIQUE (organization_id, id),
        FOREIGN KEY (organization_id, bank_account_id)
            REFERENCES bank_accounts (organization_id, id),
        FOREIGN KEY (organization_id, decided_by)
            REFERENCES memberships (organization_id, user_id),
        CHECK (action = 'close' OR reason IS NOT NULL)
    )
    """,
    "CREATE INDEX period_events_lookup_idx ON period_events (bank_account_id, period, seq)",
    "ALTER TABLE period_events ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE period_events FORCE ROW LEVEL SECURITY",
    f"""
    CREATE POLICY organization_isolation ON period_events
        USING (organization_id = {TENANT}) WITH CHECK (organization_id = {TENANT})
    """,
    "GRANT SELECT, INSERT ON period_events TO concilia_app, concilia_worker",
    """
    CREATE VIEW period_status WITH (security_invoker = true) AS
    SELECT DISTINCT ON (organization_id, bank_account_id, period)
           organization_id, bank_account_id, period, action = 'close' AS closed, decided_at
    FROM period_events
    ORDER BY organization_id, bank_account_id, period, seq DESC
    """,
    "GRANT SELECT ON period_status TO concilia_app, concilia_worker",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
