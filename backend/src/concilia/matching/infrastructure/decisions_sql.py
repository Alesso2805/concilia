from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from concilia.audit.application.recorder import AuditRecorder
from concilia.matching.application.decisions import BATCH_SCORE, StoredDecision
from concilia.matching.domain.decisions import Action, MatchState
from concilia.matching.domain.inbox import MatchStatus
from concilia.matching.domain.model import DifferenceReason
from concilia.shared.infrastructure.db import lock_organization, organization_transaction


class SqlDecisionStore:
    def __init__(self, connection: AsyncConnection, audit: AuditRecorder) -> None:
        self._connection = connection
        self.audit = audit

    async def lock_organization(self, organization_id: UUID) -> None:
        await lock_organization(self._connection, organization_id)

    async def match_state(self, match_id: UUID) -> MatchState | None:
        row = (
            await self._connection.execute(
                text(
                    """SELECT s.status, m.created_by,
                              (SELECT decided_by FROM match_decisions
                               WHERE match_id = m.id AND action = 'confirm') AS confirmed_by,
                              (SELECT coalesce(sum(b.amount_cents), 0)
                               FROM match_items i JOIN bank_movements b
                                   ON b.id = i.bank_movement_id
                               WHERE i.match_id = m.id)::bigint
                            - (SELECT coalesce(sum(applied_cents), 0)
                               FROM match_items WHERE match_id = m.id)::bigint AS difference,
                              EXISTS (
                                  SELECT 1 FROM match_items i
                                  JOIN bank_movements b ON b.id = i.bank_movement_id
                                  JOIN period_status p
                                      ON p.bank_account_id = b.bank_account_id
                                     AND p.period = date_trunc('month', b.booked_on)::date
                                  WHERE i.match_id = m.id AND p.closed
                              ) AS closed
                       FROM matches m JOIN match_status s ON s.match_id = m.id
                       WHERE m.id = :id"""
                ),
                {"id": match_id},
            )
        ).first()
        if row is None:
            return None
        return MatchState(
            MatchStatus(row.status), row.created_by, row.confirmed_by, row.difference, row.closed
        )

    async def find_decision(self, decision_id: UUID) -> StoredDecision | None:
        row = (
            await self._connection.execute(
                text(
                    """SELECT id, match_id, action, reason, difference_reason, difference_note,
                              decided_by, decided_at
                       FROM match_decisions WHERE id = :id"""
                ),
                {"id": decision_id},
            )
        ).first()
        if row is None:
            return None
        return StoredDecision(
            row.id,
            row.match_id,
            Action(row.action),
            row.reason,
            DifferenceReason(row.difference_reason) if row.difference_reason else None,
            row.difference_note,
            row.decided_by,
            row.decided_at,
        )

    async def batch_candidates(
        self, bank_account_id: UUID, period: date, status: str
    ) -> list[UUID]:
        rows = await self._connection.execute(
            text(
                """SELECT m.id FROM matches m JOIN match_status s ON s.match_id = m.id
                   WHERE m.bank_account_id = :account AND m.score = :score
                     AND s.status = :status
                     AND EXISTS (
                         SELECT 1 FROM match_items c
                         JOIN bank_movements b ON b.id = c.bank_movement_id
                         WHERE c.match_id = m.id AND b.booked_on >= :period
                           AND b.booked_on < CAST(:period AS date) + interval '1 month'
                     )
                   ORDER BY m.id"""
            ),
            {"account": bank_account_id, "period": period, "status": status, "score": BATCH_SCORE},
        )
        return list(rows.scalars())

    async def insert_decision(self, organization_id: UUID, decision: StoredDecision) -> None:
        await self._connection.execute(
            text(
                """INSERT INTO match_decisions (id, organization_id, match_id, action, reason,
                                                difference_reason, difference_note, decided_by,
                                                decided_at)
                   VALUES (:id, :org, :match, :action, :reason, :difference_reason, :note,
                           :decided_by, :decided_at)"""
            ),
            {
                "id": decision.id,
                "org": organization_id,
                "match": decision.match_id,
                "action": decision.action.value,
                "reason": decision.reason,
                "difference_reason": (
                    decision.difference_reason.value if decision.difference_reason else None
                ),
                "note": decision.difference_note,
                "decided_by": decision.decided_by,
                "decided_at": decision.decided_at,
            },
        )


class SqlDecisionTransactions:
    def __init__(
        self, engine: AsyncEngine, audit_factory: Callable[[AsyncConnection], AuditRecorder]
    ) -> None:
        self._engine = engine
        self._audit_factory = audit_factory

    def store(self, connection: AsyncConnection) -> SqlDecisionStore:
        return SqlDecisionStore(connection, self._audit_factory(connection))

    @asynccontextmanager
    async def organization(self, organization_id: UUID) -> AsyncIterator[SqlDecisionStore]:
        async with organization_transaction(self._engine, organization_id) as connection:
            yield self.store(connection)
