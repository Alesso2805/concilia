from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import asynccontextmanager
from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from concilia.audit.application.recorder import AuditRecorder
from concilia.periods.application.closing import PeriodAction, PeriodEvent
from concilia.periods.application.pending import PendingMatchesQuery
from concilia.shared.infrastructure.db import lock_organization, organization_transaction
from concilia.shared.kernel.ids import IdConflictError


class SqlPeriodQueries:
    def __init__(self, connection: AsyncConnection) -> None:
        self._connection = connection

    async def closed_periods(self, bank_account_id: UUID, periods: Iterable[date]) -> set[date]:
        wanted = sorted(set(periods))
        if not wanted:
            return set()
        rows = await self._connection.execute(
            text(
                """SELECT period FROM period_status
                   WHERE bank_account_id = :account AND period = ANY(:periods) AND closed"""
            ),
            {"account": bank_account_id, "periods": wanted},
        )
        return set(rows.scalars())


class SqlPeriodStore:
    def __init__(
        self, connection: AsyncConnection, audit: AuditRecorder, pending: PendingMatchesQuery
    ) -> None:
        self._connection = connection
        self.audit = audit
        self.pending = pending

    async def lock_organization(self, organization_id: UUID) -> None:
        await lock_organization(self._connection, organization_id)

    async def account_exists(self, bank_account_id: UUID) -> bool:
        found = await self._connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM bank_accounts WHERE id = :id)"),
            {"id": bank_account_id},
        )
        return bool(found)

    async def is_closed(self, bank_account_id: UUID, period: date) -> bool:
        return bool(
            await SqlPeriodQueries(self._connection).closed_periods(bank_account_id, {period})
        )

    async def find_event(self, event_id: UUID) -> PeriodEvent | None:
        row = (
            await self._connection.execute(
                text(
                    """SELECT id, bank_account_id, period, action, reason, decided_by, decided_at
                       FROM period_events WHERE id = :id"""
                ),
                {"id": event_id},
            )
        ).first()
        if row is None:
            return None
        return PeriodEvent(
            row.id,
            row.bank_account_id,
            row.period,
            PeriodAction(row.action),
            row.reason,
            row.decided_by,
            row.decided_at,
        )

    async def insert_event(self, organization_id: UUID, event: PeriodEvent) -> None:
        try:
            await self._connection.execute(
                text(
                    """INSERT INTO period_events (id, organization_id, bank_account_id, period,
                                                 action, reason, decided_by, decided_at)
                       VALUES (:id, :org, :account, :period, :action, :reason, :by, :at)"""
                ),
                {
                    "id": event.id,
                    "org": organization_id,
                    "account": event.bank_account_id,
                    "period": event.period,
                    "action": event.action.value,
                    "reason": event.reason,
                    "by": event.decided_by,
                    "at": event.decided_at,
                },
            )
        except IntegrityError as error:
            raise IdConflictError from error


class SqlPeriodTransactions:
    def __init__(
        self,
        engine: AsyncEngine,
        audit_factory: Callable[[AsyncConnection], AuditRecorder],
        pending_factory: Callable[[AsyncConnection], PendingMatchesQuery],
    ) -> None:
        self._engine = engine
        self._audit_factory = audit_factory
        self._pending_factory = pending_factory

    def store(self, connection: AsyncConnection) -> SqlPeriodStore:
        return SqlPeriodStore(
            connection, self._audit_factory(connection), self._pending_factory(connection)
        )

    @asynccontextmanager
    async def organization(self, organization_id: UUID) -> AsyncIterator[SqlPeriodStore]:
        async with organization_transaction(self._engine, organization_id) as connection:
            yield self.store(connection)
