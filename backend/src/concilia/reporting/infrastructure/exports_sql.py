from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from concilia.audit.application.recorder import AuditRecorder
from concilia.reporting.application.exports import (
    KIND,
    ExportRequest,
    JobStatus,
    StoredExport,
)
from concilia.reporting.domain.workbook import MatchLine, PendingLine
from concilia.reporting.infrastructure.dashboard_sql import CREDITS, SqlDashboardStore
from concilia.shared.infrastructure.db import organization_transaction
from concilia.shared.infrastructure.jobs import enqueue
from concilia.shared.kernel.ids import IdConflictError

MATCH_LINES = """
    SELECT m.id, s.status, m.source, m.rule, cr.booked_on, cr.descriptions, cr.credits_cents,
           rc.documents, rc.customers, rc.applied_cents, conf.difference_reason,
           cu.display_name AS confirmed_by, conf.decided_at AS confirmed_at,
           au.display_name AS approved_by, appr.decided_at AS approved_at
    FROM match_status s
    JOIN matches m ON m.id = s.match_id
    CROSS JOIN LATERAL (
        SELECT min(b.booked_on) AS booked_on,
               array_agg(b.description ORDER BY b.booked_on, b.id) AS descriptions,
               sum(b.amount_cents)::bigint AS credits_cents
        FROM match_items c JOIN bank_movements b ON b.id = c.bank_movement_id
        WHERE c.match_id = m.id
    ) cr
    CROSS JOIN LATERAL (
        SELECT array_agg(r.doc_number ORDER BY r.doc_number_norm) AS documents,
               array_agg(DISTINCT r.customer_name) AS customers,
               sum(i.applied_cents)::bigint AS applied_cents
        FROM match_items i JOIN receivables r ON r.id = i.receivable_id
        WHERE i.match_id = m.id
    ) rc
    LEFT JOIN match_decisions conf ON conf.match_id = m.id AND conf.action = 'confirm'
    LEFT JOIN users cu ON cu.id = conf.decided_by
    LEFT JOIN match_decisions appr ON appr.match_id = m.id AND appr.action = 'approve'
    LEFT JOIN users au ON au.id = appr.decided_by
    WHERE s.bank_account_id = :account AND s.status = ANY(:statuses)
      AND EXISTS (
          SELECT 1 FROM match_items c JOIN bank_movements b ON b.id = c.bank_movement_id
          WHERE c.match_id = m.id AND b.booked_on BETWEEN :start AND :end)
    ORDER BY cr.booked_on, m.id
"""


def _request(row: Any) -> ExportRequest:
    return ExportRequest(
        row.id,
        UUID(row.payload["bank_account_id"]),
        date.fromisoformat(row.payload["period"]),
        row.created_by,
        cast(JobStatus, row.status),
        row.error_code,
        row.expires_at,
    )


class SqlExportStore(SqlDashboardStore):
    def __init__(self, connection: AsyncConnection, audit: AuditRecorder) -> None:
        super().__init__(connection)
        self.audit = audit

    async def account_label(self, bank_account_id: UUID) -> str | None:
        row = (
            await self._connection.execute(
                text("SELECT bank, alias, number_last4 FROM bank_accounts WHERE id = :id"),
                {"id": bank_account_id},
            )
        ).first()
        return f"{row.bank} · {row.alias} ({row.number_last4})" if row else None

    async def find_request(self, request_id: UUID) -> ExportRequest | None:
        row = (
            await self._connection.execute(
                text(
                    """SELECT j.id, j.payload, j.created_by, j.status, j.error_code, e.expires_at
                       FROM jobs j LEFT JOIN exports e ON e.job_id = j.id
                       WHERE j.id = :id AND j.kind = :kind"""
                ),
                {"id": request_id, "kind": KIND},
            )
        ).first()
        return _request(row) if row else None

    async def enqueue(
        self, organization_id: UUID, request: ExportRequest, requested_by: UUID, now: datetime
    ) -> None:
        try:
            await enqueue(
                self._connection,
                job_id=request.id,
                kind=KIND,
                now=now,
                organization_id=organization_id,
                payload={
                    "bank_account_id": str(request.bank_account_id),
                    "period": request.period.isoformat(),
                },
                created_by=requested_by,
            )
        except IntegrityError as error:
            raise IdConflictError from error

    async def find_export(self, job_id: UUID) -> StoredExport | None:
        row = (
            await self._connection.execute(
                text(
                    """SELECT id, job_id, bank_account_id, period, content, created_by,
                              created_at, expires_at
                       FROM exports WHERE job_id = :job"""
                ),
                {"job": job_id},
            )
        ).first()
        if row is None:
            return None
        return StoredExport(
            row.id,
            row.job_id,
            row.bank_account_id,
            row.period,
            bytes(row.content),
            row.created_by,
            row.created_at,
            row.expires_at,
        )

    async def insert_export(self, organization_id: UUID, export: StoredExport) -> None:
        await self._connection.execute(
            text(
                """INSERT INTO exports (id, organization_id, bank_account_id, period, job_id,
                                       content, created_by, created_at, expires_at)
                   VALUES (:id, :org, :account, :period, :job, :content, :by, :at, :expires)"""
            ),
            {
                "id": export.id,
                "org": organization_id,
                "account": export.bank_account_id,
                "period": export.period,
                "job": export.job_id,
                "content": export.content,
                "by": export.created_by,
                "at": export.created_at,
                "expires": export.expires_at,
            },
        )

    async def match_lines(
        self, bank_account_id: UUID, start: date, end: date, statuses: Sequence[str]
    ) -> list[MatchLine]:
        rows = await self._connection.execute(
            text(MATCH_LINES),
            {"account": bank_account_id, "start": start, "end": end, "statuses": list(statuses)},
        )
        return [
            MatchLine(
                row.id,
                row.status,
                row.source,
                row.rule,
                row.booked_on,
                list(row.descriptions),
                row.credits_cents,
                list(row.documents or []),
                list(row.customers or []),
                row.applied_cents or 0,
                row.difference_reason,
                row.confirmed_by,
                row.confirmed_at,
                row.approved_by,
                row.approved_at,
            )
            for row in rows
        ]

    async def pending_lines(self, bank_account_id: UUID, until: date) -> list[PendingLine]:
        rows = await self._connection.execute(
            text(
                f"""SELECT c.booked_on, c.description, c.operation_number, c.amount_cents,
                           c.status
                    FROM ({CREDITS} AND b.booked_on <= :until) c
                    WHERE c.status <> 'approved'
                    ORDER BY c.booked_on, c.id"""  # noqa: S608
            ),
            {"account": bank_account_id, "until": until},
        )
        return [
            PendingLine(
                row.booked_on, row.description, row.operation_number, row.amount_cents, row.status
            )
            for row in rows
        ]


class SqlExportTransactions:
    def __init__(
        self, engine: AsyncEngine, audit_factory: Callable[[AsyncConnection], AuditRecorder]
    ) -> None:
        self._engine = engine
        self._audit_factory = audit_factory

    def store(self, connection: AsyncConnection) -> SqlExportStore:
        return SqlExportStore(connection, self._audit_factory(connection))

    @asynccontextmanager
    async def organization(self, organization_id: UUID) -> AsyncIterator[SqlExportStore]:
        async with organization_transaction(self._engine, organization_id) as connection:
            yield self.store(connection)
