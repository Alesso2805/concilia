from alembic import op

revision = "0004"
down_revision = "0003"

TENANT = "NULLIF(current_setting('app.org_id', true), '')::uuid"

STATEMENTS = [
    """
    CREATE TABLE bank_accounts (
        id uuid PRIMARY KEY,
        organization_id uuid NOT NULL REFERENCES organizations (id),
        bank text NOT NULL CHECK (length(bank) BETWEEN 1 AND 60),
        currency text NOT NULL CHECK (currency = 'PEN'),
        alias text NOT NULL CHECK (length(alias) BETWEEN 1 AND 80),
        number_last4 text NOT NULL CHECK (number_last4 ~ '^[0-9]{4}$'),
        created_at timestamptz NOT NULL,
        archived_at timestamptz,
        UNIQUE (organization_id, id)
    )
    """,
    "CREATE INDEX bank_accounts_organization_idx ON bank_accounts (organization_id)",
    """
    CREATE TABLE import_profiles (
        id uuid PRIMARY KEY,
        organization_id uuid NOT NULL REFERENCES organizations (id),
        kind text NOT NULL CHECK (kind IN ('bank_statement', 'receivables')),
        bank_account_id uuid,
        name text NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
        config jsonb NOT NULL,
        created_at timestamptz NOT NULL,
        archived_at timestamptz,
        UNIQUE (organization_id, id),
        FOREIGN KEY (organization_id, bank_account_id)
            REFERENCES bank_accounts (organization_id, id),
        CHECK ((kind = 'bank_statement') = (bank_account_id IS NOT NULL))
    )
    """,
    "CREATE INDEX import_profiles_organization_idx ON import_profiles (organization_id, kind)",
    *(
        statement
        for table in ("bank_accounts", "import_profiles")
        for statement in (
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
            f"""
            CREATE POLICY organization_isolation ON {table}
                USING (organization_id = {TENANT}) WITH CHECK (organization_id = {TENANT})
            """,
            f"GRANT SELECT, INSERT ON {table} TO concilia_app, concilia_worker",
        )
    ),
    """
    GRANT UPDATE (bank, alias, number_last4, archived_at) ON bank_accounts
        TO concilia_app, concilia_worker
    """,
    "GRANT UPDATE (name, config, archived_at) ON import_profiles TO concilia_app, concilia_worker",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
