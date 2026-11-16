from alembic import op

revision = "0010"
down_revision = "0009"

# sum() over bigint returns numeric in PostgreSQL, which drivers read as decimals; balances are
# money and stay integer cents (CLAUDE.md rule 1). A view column's type cannot change in place.
STATEMENTS = [
    "DROP VIEW receivable_balances",
    """
    CREATE VIEW receivable_balances WITH (security_invoker = true) AS
    SELECT r.id AS receivable_id, r.organization_id, r.amount_cents,
           (r.amount_cents
               - coalesce(sum(i.applied_cents) FILTER (WHERE s.status = 'approved'), 0)
           )::bigint AS open_cents,
           (r.amount_cents
               - coalesce(sum(i.applied_cents)
                          FILTER (WHERE s.status IN ('proposed', 'confirmed', 'approved')), 0)
           )::bigint AS available_cents
    FROM receivables r
    LEFT JOIN match_items i ON i.receivable_id = r.id
    LEFT JOIN match_status s ON s.match_id = i.match_id
    GROUP BY r.id
    """,
    "GRANT SELECT ON receivable_balances TO concilia_app, concilia_worker",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
