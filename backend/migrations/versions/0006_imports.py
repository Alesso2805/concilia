from alembic import op

revision = "0006"
down_revision = "0005"

TENANT = "NULLIF(current_setting('app.org_id', true), '')::uuid"
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 10_000

STATEMENTS = [
    f"""
    CREATE TABLE import_files (
        id uuid PRIMARY KEY,
        organization_id uuid NOT NULL REFERENCES organizations (id),
        kind text NOT NULL CHECK (kind IN ('bank_statement', 'receivables')),
        bank_account_id uuid,
        import_profile_id uuid NOT NULL,
        profile_snapshot jsonb NOT NULL,
        filename text NOT NULL CHECK (length(filename) BETWEEN 1 AND 255),
        sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{{64}}$'),
        size_bytes integer NOT NULL CHECK (size_bytes BETWEEN 1 AND {MAX_FILE_BYTES}),
        content bytea NOT NULL,
        status text NOT NULL CHECK (status IN ('uploaded', 'parsing', 'previewed', 'failed',
                                               'confirmed', 'discarded', 'voided')),
        error_code text,
        row_count integer CHECK (row_count BETWEEN 0 AND {MAX_ROWS}),
        created_by uuid NOT NULL,
        created_at timestamptz NOT NULL,
        confirmed_at timestamptz,
        discarded_at timestamptz,
        voided_at timestamptz,
        void_reason text CHECK (length(void_reason) BETWEEN 1 AND 500),
        UNIQUE (organization_id, id),
        FOREIGN KEY (organization_id, bank_account_id)
            REFERENCES bank_accounts (organization_id, id),
        FOREIGN KEY (organization_id, import_profile_id)
            REFERENCES import_profiles (organization_id, id),
        FOREIGN KEY (organization_id, created_by)
            REFERENCES memberships (organization_id, user_id),
        CHECK ((kind = 'bank_statement') = (bank_account_id IS NOT NULL)),
        CHECK ((status = 'voided') = (voided_at IS NOT NULL AND void_reason IS NOT NULL))
    )
    """,
    """
    CREATE UNIQUE INDEX import_files_confirmed_sha256_idx
        ON import_files (bank_account_id, sha256)
        WHERE status = 'confirmed'
    """,
    "CREATE INDEX import_files_listing_idx ON import_files (organization_id, created_at, id)",
    """
    CREATE TABLE import_rows (
        id uuid PRIMARY KEY,
        organization_id uuid NOT NULL,
        import_file_id uuid NOT NULL,
        row_number integer NOT NULL CHECK (row_number > 0),
        parsed jsonb NOT NULL,
        status text NOT NULL CHECK (status IN ('ok', 'error', 'duplicate', 'closed_period',
                                               'conflict')),
        error_code text,
        UNIQUE (organization_id, id),
        UNIQUE (import_file_id, row_number),
        FOREIGN KEY (organization_id, import_file_id)
            REFERENCES import_files (organization_id, id),
        CHECK ((status = 'error') = (error_code IS NOT NULL))
    )
    """,
    """
    CREATE TABLE bank_movements (
        id uuid PRIMARY KEY,
        organization_id uuid NOT NULL,
        bank_account_id uuid NOT NULL,
        import_file_id uuid NOT NULL,
        booked_on date NOT NULL,
        amount_cents bigint NOT NULL CHECK (amount_cents <> 0),
        description text NOT NULL,
        description_norm text NOT NULL,
        operation_number text,
        fingerprint text NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
        doc_refs text[] NOT NULL,
        created_at timestamptz NOT NULL,
        voided_at timestamptz,
        UNIQUE (organization_id, id),
        FOREIGN KEY (organization_id, bank_account_id)
            REFERENCES bank_accounts (organization_id, id),
        FOREIGN KEY (organization_id, import_file_id)
            REFERENCES import_files (organization_id, id)
    )
    """,
    """
    CREATE UNIQUE INDEX bank_movements_fingerprint_idx
        ON bank_movements (bank_account_id, fingerprint)
        WHERE voided_at IS NULL
    """,
    "CREATE INDEX bank_movements_booked_idx ON bank_movements (bank_account_id, booked_on, id)",
    "CREATE INDEX bank_movements_file_idx ON bank_movements (import_file_id)",
    *(
        statement
        for table in ("import_files", "import_rows", "bank_movements")
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
    GRANT UPDATE (status, error_code, row_count, confirmed_at, discarded_at, voided_at,
                  void_reason)
        ON import_files TO concilia_app, concilia_worker
    """,
    "GRANT UPDATE (voided_at) ON bank_movements TO concilia_app, concilia_worker",
    "GRANT DELETE ON import_rows TO concilia_app, concilia_worker",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
