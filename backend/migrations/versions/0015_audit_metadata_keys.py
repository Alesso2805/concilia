from alembic import op

revision = "0015"
down_revision = "0014"

# Mirrors audit.domain.ALLOWED_METADATA_KEYS (a test compares them) so that events written by
# SQL functions, which skip the domain, cannot carry customer data either.
STATEMENTS = [
    """
    ALTER TABLE audit_events ADD CONSTRAINT audit_events_metadata_keys CHECK (
        jsonb_typeof(metadata) = 'object'
        AND metadata - ARRAY['fields', 'kind', 'roles', 'source'] = '{}'::jsonb
    )
    """,
    """
    CREATE INDEX audit_events_actor_idx ON audit_events (organization_id, actor_user_id, seq)
    """,
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
