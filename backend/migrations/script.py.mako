from alembic import op

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}

STATEMENTS: list[str] = []


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
