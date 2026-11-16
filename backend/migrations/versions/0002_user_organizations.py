from alembic import op

revision = "0002"
down_revision = "0001"

STATEMENTS = [
    """
    CREATE FUNCTION app_user_orgs(p_user_id uuid)
        RETURNS TABLE (organization_id uuid, name text, is_demo boolean, roles text[])
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
    AS $$
        SELECT o.id, o.name, o.is_demo,
               coalesce(array_agg(r.role ORDER BY r.role) FILTER (WHERE r.role IS NOT NULL),
                        '{}')
        FROM memberships m
        JOIN organizations o ON o.id = m.organization_id
        LEFT JOIN member_roles r
            ON r.organization_id = m.organization_id AND r.user_id = m.user_id
        WHERE m.user_id = p_user_id AND m.removed_at IS NULL
        GROUP BY o.id, o.name, o.is_demo
        ORDER BY o.name, o.id
    $$
    """,
    "REVOKE ALL ON FUNCTION app_user_orgs(uuid) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION app_user_orgs(uuid) TO concilia_app",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
