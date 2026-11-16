from alembic import op

revision = "0008"
down_revision = "0007"

TENANT = "NULLIF(current_setting('app.org_id', true), '')::uuid"

STATEMENTS = [
    """
    CREATE TABLE receivables (
        id uuid PRIMARY KEY,
        organization_id uuid NOT NULL REFERENCES organizations (id),
        import_file_id uuid NOT NULL,
        customer_name text NOT NULL CHECK (length(customer_name) BETWEEN 1 AND 200),
        customer_name_norm text NOT NULL,
        customer_tax_id text CHECK (customer_tax_id ~ '^([0-9]{8}|[0-9]{11})$'),
        doc_number text NOT NULL CHECK (length(doc_number) BETWEEN 1 AND 40),
        doc_number_norm text NOT NULL,
        issued_on date NOT NULL,
        due_on date NOT NULL CHECK (due_on >= issued_on),
        amount_cents bigint NOT NULL CHECK (amount_cents > 0),
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        cancelled_at timestamptz,
        cancel_reason text CHECK (length(cancel_reason) BETWEEN 1 AND 500),
        UNIQUE (organization_id, id),
        UNIQUE (organization_id, doc_number_norm),
        FOREIGN KEY (organization_id, import_file_id)
            REFERENCES import_files (organization_id, id),
        CHECK ((cancelled_at IS NULL) = (cancel_reason IS NULL))
    )
    """,
    "CREATE INDEX receivables_due_idx ON receivables (organization_id, due_on, id)",
    """
    CREATE INDEX receivables_customer_idx
        ON receivables (organization_id, customer_tax_id, customer_name_norm)
    """,
    "CREATE INDEX receivables_file_idx ON receivables (import_file_id)",
    """
    CREATE UNIQUE INDEX import_files_confirmed_receivables_idx
        ON import_files (organization_id, sha256)
        WHERE status = 'confirmed' AND kind = 'receivables'
    """,
    "ALTER TABLE receivables ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE receivables FORCE ROW LEVEL SECURITY",
    f"""
    CREATE POLICY organization_isolation ON receivables
        USING (organization_id = {TENANT}) WITH CHECK (organization_id = {TENANT})
    """,
    "GRANT SELECT, INSERT ON receivables TO concilia_app, concilia_worker",
    """
    GRANT UPDATE (due_on, amount_cents, updated_at, cancelled_at, cancel_reason) ON receivables
        TO concilia_app, concilia_worker
    """,
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
