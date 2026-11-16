from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from concilia.audit.infrastructure.sql import SqlAuditRecorder
from concilia.matching.infrastructure.runs_sql import SqlRunTransactions
from concilia.periods.infrastructure.sql import SqlPeriodQueries
from tests.support.database import DatabaseUrls
from tests.support.imports import NOW, Setup, statement_setup

pytestmark = pytest.mark.anyio

ROWS = 3_000
STALE = ("receivables", "match_items", "matches", "match_decisions", "bank_movements")
SEED = [
    """INSERT INTO import_files (id, organization_id, kind, bank_account_id, import_profile_id,
                                 profile_snapshot, filename, sha256, size_bytes, content, status,
                                 created_by, created_at)
       VALUES (md5('plans')::uuid, :org, 'bank_statement', :account, :profile, '{}', 'p.csv',
               repeat('d', 64), 3, 'abc', 'confirmed', :user, :now)""",
    """INSERT INTO bank_movements (id, organization_id, bank_account_id, import_file_id,
                                   booked_on, amount_cents, description, description_norm,
                                   fingerprint, doc_refs, created_at)
       SELECT md5('pm' || n)::uuid, :org, :account, md5('plans')::uuid,
              DATE '2027-01-01' + (n % 28), 1000 + n, 'PAGO', 'PAGO',
              md5('pm' || n) || md5('pf' || n), '{}', :now
       FROM generate_series(1, :rows) n""",
    """INSERT INTO receivables (id, organization_id, import_file_id, customer_name,
                                customer_name_norm, doc_number, doc_number_norm, issued_on,
                                due_on, amount_cents, created_at, updated_at)
       SELECT md5('pr' || n)::uuid, :org, md5('plans')::uuid, 'Cliente', 'CLIENTE',
              'F009-' || n, 'F009-' || n, DATE '2026-12-15', DATE '2027-01-15',
              2000 + n, :now, :now
       FROM generate_series(1, :rows) n""",
    """INSERT INTO matches (id, organization_id, bank_account_id, source, created_by,
                           created_at)
       SELECT md5('px' || n)::uuid, :org, :account, 'manual', :user, :now
       FROM generate_series(1, :rows / 2) n""",
    """INSERT INTO match_items (id, organization_id, match_id, bank_movement_id)
       SELECT md5('pi' || n)::uuid, :org, md5('px' || n)::uuid, md5('pm' || n)::uuid
       FROM generate_series(1, :rows / 2) n""",
    """INSERT INTO match_items (id, organization_id, match_id, receivable_id, applied_cents)
       SELECT md5('pj' || n)::uuid, :org, md5('px' || n)::uuid, md5('pr' || n)::uuid, 1000 + n
       FROM generate_series(1, :rows / 2) n""",
    """INSERT INTO match_decisions (id, organization_id, match_id, action, decided_by,
                                   decided_at)
       SELECT md5('pd' || n)::uuid, :org, md5('px' || n)::uuid, 'confirm', :user, :now
       FROM generate_series(1, :rows / 2) n""",
]


@pytest.fixture
async def books(owner_engine: AsyncEngine) -> Setup:
    setup = await statement_setup(owner_engine)
    params = {
        "org": setup.organization_id,
        "account": setup.account_id,
        "profile": setup.profile_id,
        "user": setup.member.user_id,
        "now": NOW,
        "rows": ROWS,
    }
    async with owner_engine.begin() as connection:
        for table in ("matches", "match_items", "match_decisions"):
            await connection.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER USER"))
        for statement in SEED:
            await connection.execute(text(statement), params)
        for table in ("matches", "match_items", "match_decisions"):
            await connection.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER USER"))
    return setup


async def test_balances_stay_fast_while_the_statistics_know_nothing_of_the_rows(
    database: DatabaseUrls, books: Setup
) -> None:
    superuser = create_async_engine(database.superuser())
    try:
        async with superuser.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(
                text(
                    """UPDATE pg_class SET reltuples = 10, relpages = 1
                       WHERE relname = ANY(:tables)"""
                ),
                {"tables": list(STALE)},
            )
            await connection.execute(
                text(
                    """DELETE FROM pg_statistic
                       WHERE starelid IN (SELECT oid FROM pg_class WHERE relname = ANY(:tables))"""
                ),
                {"tables": list(STALE)},
            )
            await connection.execute(text("SET LOCAL ROLE concilia_app"))
            await connection.execute(
                text("SELECT set_config('app.org_id', :org, true)"),
                {"org": str(books.organization_id)},
            )
            await connection.execute(text("SET LOCAL statement_timeout = '5s'"))
            store = SqlRunTransactions(superuser, SqlAuditRecorder, SqlPeriodQueries).store(
                connection
            )
            engine_input = await store.engine_input(
                books.organization_id, books.account_id, date(2027, 1, 1)
            )
            await transaction.rollback()
    finally:
        await superuser.dispose()

    assert len(engine_input.receivables) == ROWS
