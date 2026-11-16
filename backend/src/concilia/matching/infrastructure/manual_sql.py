from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from uuid import UUID, uuid7

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from concilia.audit.application.recorder import AuditRecorder
from concilia.matching.application.manual import (
    CreditFacts,
    ReceivableFacts,
    StoredManualMatch,
)
from concilia.matching.domain.manual import ManualApplication, ManualMatch
from concilia.matching.infrastructure.decisions_sql import SqlDecisionStore
from concilia.shared.infrastructure.db import organization_transaction


class SqlManualStore(SqlDecisionStore):
    async def credit_facts(self, credit_ids: list[UUID]) -> list[CreditFacts]:
        rows = await self._connection.execute(
            text(
                """SELECT b.id, b.bank_account_id,
                          b.amount_cents > 0 AND b.voided_at IS NULL AS live_credit,
                          NOT EXISTS (
                              SELECT 1 FROM match_items i
                              JOIN match_status s ON s.match_id = i.match_id
                              WHERE i.bank_movement_id = b.id
                                AND s.status IN ('proposed', 'confirmed', 'approved')
                          ) AS free
                   FROM bank_movements b WHERE b.id = ANY(:ids)"""
            ),
            {"ids": credit_ids},
        )
        return [CreditFacts(row.id, row.bank_account_id, row.live_credit, row.free) for row in rows]

    async def receivable_facts(self, receivable_ids: list[UUID]) -> list[ReceivableFacts]:
        rows = await self._connection.execute(
            text(
                """SELECT r.id, r.cancelled_at IS NOT NULL AS cancelled, b.available_cents
                   FROM receivables r JOIN receivable_balances b ON b.receivable_id = r.id
                   WHERE r.id = ANY(:ids)"""
            ),
            {"ids": receivable_ids},
        )
        return [ReceivableFacts(row.id, row.cancelled, row.available_cents) for row in rows]

    async def find_manual_match(self, match_id: UUID) -> StoredManualMatch | None:
        match = (
            await self._connection.execute(
                text("SELECT bank_account_id, created_by FROM matches WHERE id = :id"),
                {"id": match_id},
            )
        ).first()
        if match is None:
            return None
        items = (
            await self._connection.execute(
                text(
                    """SELECT bank_movement_id, receivable_id, applied_cents FROM match_items
                       WHERE match_id = :id ORDER BY id"""
                ),
                {"id": match_id},
            )
        ).all()
        return StoredManualMatch(
            match_id,
            match.bank_account_id,
            match.created_by,
            ManualMatch(
                tuple(item.bank_movement_id for item in items if item.bank_movement_id),
                tuple(
                    ManualApplication(item.receivable_id, item.applied_cents)
                    for item in items
                    if item.receivable_id
                ),
            ),
        )

    async def insert_manual_match(
        self, organization_id: UUID, stored: StoredManualMatch, now: datetime
    ) -> None:
        await self._connection.execute(
            text(
                """INSERT INTO matches (id, organization_id, bank_account_id, source, created_by,
                                        created_at)
                   VALUES (:id, :org, :account, 'manual', :created_by, :now)"""
            ),
            {
                "id": stored.id,
                "org": organization_id,
                "account": stored.bank_account_id,
                "created_by": stored.created_by,
                "now": now,
            },
        )
        items = [
            {"movement": credit, "receivable": None, "applied": None}
            for credit in stored.match.credit_ids
        ] + [
            {"movement": None, "receivable": a.receivable_id, "applied": a.applied_cents}
            for a in stored.match.applications
        ]
        await self._connection.execute(
            text(
                """INSERT INTO match_items (id, organization_id, match_id, bank_movement_id,
                                            receivable_id, applied_cents)
                   VALUES (:id, :org, :match, :movement, :receivable, :applied)"""
            ),
            [{"id": uuid7(), "org": organization_id, "match": stored.id, **item} for item in items],
        )


class SqlManualTransactions:
    def __init__(
        self, engine: AsyncEngine, audit_factory: Callable[[AsyncConnection], AuditRecorder]
    ) -> None:
        self._engine = engine
        self._audit_factory = audit_factory

    @asynccontextmanager
    async def organization(self, organization_id: UUID) -> AsyncIterator[SqlManualStore]:
        async with organization_transaction(self._engine, organization_id) as connection:
            yield SqlManualStore(connection, self._audit_factory(connection))
