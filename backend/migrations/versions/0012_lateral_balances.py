from alembic import op

revision = "0012"
down_revision = "0011"

# Each balance is summed from that receivable's own items through their indexes. The grouped
# join it replaces depended on fresh statistics: right after a demo inserted its rows, before
# autovacuum analyzed them, the planner chose nested loops over the whole view and the engine
# input and the match detail ran for minutes.
STATEMENTS = [
    "DROP VIEW receivable_balances",
    """
    CREATE VIEW receivable_balances WITH (security_invoker = true) AS
    SELECT r.id AS receivable_id, r.organization_id, r.amount_cents,
           (r.amount_cents - coalesce(applied.approved, 0))::bigint AS open_cents,
           (r.amount_cents - coalesce(applied.active, 0))::bigint AS available_cents
    FROM receivables r
    LEFT JOIN LATERAL (
        SELECT sum(i.applied_cents) FILTER (WHERE s.status = 'approved') AS approved,
               sum(i.applied_cents)
                   FILTER (WHERE s.status IN ('proposed', 'confirmed', 'approved')) AS active
        FROM match_items i JOIN match_status s ON s.match_id = i.match_id
        WHERE i.receivable_id = r.id
    ) applied ON true
    """,
    "GRANT SELECT ON receivable_balances TO concilia_app, concilia_worker",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
