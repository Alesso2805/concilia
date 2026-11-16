import json
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from uuid import UUID, uuid7

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from concilia.audit.application.recorder import AuditRecorder
from concilia.banking.application.profile_config import ProfileKind
from concilia.imports.application.service import ActiveProfile
from concilia.imports.domain.model import FileStatus, ImportFile, ImportRow, RowPage, RowStatus
from concilia.periods.application.queries import PeriodQueries
from concilia.shared.infrastructure.db import lock_organization, organization_transaction
from concilia.shared.infrastructure.jobs import enqueue
from concilia.shared.kernel.ids import IdConflictError

FILE_COLUMNS = """id, kind, bank_account_id, import_profile_id, profile_snapshot, filename, sha256,
                  size_bytes, status, error_code, row_count, created_by, created_at, confirmed_at,
                  discarded_at, voided_at"""
FILE_FIELDS = frozenset(
    {
        "status",
        "error_code",
        "row_count",
        "confirmed_at",
        "discarded_at",
        "voided_at",
        "void_reason",
    }
)


def _file(row: Any) -> ImportFile:
    return ImportFile(
        row.id,
        row.kind,
        row.bank_account_id,
        row.import_profile_id,
        dict(row.profile_snapshot),
        row.filename,
        row.sha256,
        row.size_bytes,
        FileStatus(row.status),
        row.error_code,
        row.row_count,
        row.created_by,
        row.created_at,
        row.confirmed_at,
        row.discarded_at,
        row.voided_at,
    )


class SqlImportStore:
    def __init__(
        self, connection: AsyncConnection, audit: AuditRecorder, periods: PeriodQueries
    ) -> None:
        self._connection = connection
        self.audit = audit
        self.periods = periods

    async def lock_organization(self, organization_id: UUID) -> None:
        await lock_organization(self._connection, organization_id)

    async def active_profile(self, profile_id: UUID) -> ActiveProfile | None:
        row = (
            await self._connection.execute(
                text(
                    """SELECT p.id, p.kind, p.bank_account_id, p.name, p.config
                       FROM import_profiles p
                       LEFT JOIN bank_accounts a ON a.id = p.bank_account_id
                       WHERE p.id = :id AND p.archived_at IS NULL AND a.archived_at IS NULL"""
                ),
                {"id": profile_id},
            )
        ).first()
        if row is None:
            return None
        return ActiveProfile(
            row.id, ProfileKind(row.kind), row.bank_account_id, row.name, dict(row.config)
        )

    async def find_file(self, file_id: UUID) -> ImportFile | None:
        row = (
            await self._connection.execute(
                text(f"SELECT {FILE_COLUMNS} FROM import_files WHERE id = :id"),  # noqa: S608
                {"id": file_id},
            )
        ).first()
        return None if row is None else _file(row)

    async def file_content(self, file_id: UUID) -> bytes:
        content: bytes = (
            await self._connection.execute(
                text("SELECT content FROM import_files WHERE id = :id"), {"id": file_id}
            )
        ).scalar_one()
        return content

    async def confirmed_with_hash(self, bank_account_id: UUID, sha256: str) -> UUID | None:
        found: UUID | None = (
            await self._connection.execute(
                text(
                    """SELECT id FROM import_files
                       WHERE bank_account_id = :account AND sha256 = :sha
                         AND status = 'confirmed'"""
                ),
                {"account": bank_account_id, "sha": sha256},
            )
        ).scalar_one_or_none()
        return found

    async def insert_file(self, organization_id: UUID, file: ImportFile, content: bytes) -> None:
        try:
            await self._connection.execute(
                text(
                    """INSERT INTO import_files (id, organization_id, kind, bank_account_id,
                                                 import_profile_id, profile_snapshot, filename,
                                                 sha256, size_bytes, content, status, created_by,
                                                 created_at)
                       VALUES (:id, :org, :kind, :account, :profile, CAST(:snapshot AS jsonb),
                               :filename, :sha, :size, :content, :status, :created_by, :now)"""
                ),
                {
                    "id": file.id,
                    "org": organization_id,
                    "kind": file.kind,
                    "account": file.bank_account_id,
                    "profile": file.import_profile_id,
                    "snapshot": json.dumps(dict(file.profile_snapshot)),
                    "filename": file.filename,
                    "sha": file.sha256,
                    "size": file.size_bytes,
                    "content": content,
                    "status": file.status.value,
                    "created_by": file.created_by,
                    "now": file.created_at,
                },
            )
        except IntegrityError as error:
            raise IdConflictError from error

    async def update_file(self, file_id: UUID, **fields: object) -> None:
        unknown = set(fields) - FILE_FIELDS
        if unknown:
            raise ValueError(sorted(unknown))
        assignments = ", ".join(f"{name} = :{name}" for name in sorted(fields))
        await self._connection.execute(
            text(f"UPDATE import_files SET {assignments} WHERE id = :id"),  # noqa: S608
            {"id": file_id, **fields},
        )

    async def replace_rows(
        self, organization_id: UUID, file_id: UUID, rows: list[ImportRow]
    ) -> None:
        await self.delete_rows(file_id)
        if not rows:
            return
        await self._connection.execute(
            text(
                """INSERT INTO import_rows (id, organization_id, import_file_id, row_number, parsed,
                                            status, error_code)
                   VALUES (:id, :org, :file, :row_number, CAST(:parsed AS jsonb), :status,
                           :error_code)"""
            ),
            [
                {
                    "id": uuid7(),
                    "org": organization_id,
                    "file": file_id,
                    "row_number": row.row_number,
                    "parsed": json.dumps(dict(row.parsed)),
                    "status": row.status.value,
                    "error_code": row.error_code,
                }
                for row in rows
            ],
        )

    async def delete_rows(self, file_id: UUID) -> None:
        await self._connection.execute(
            text("DELETE FROM import_rows WHERE import_file_id = :file"), {"file": file_id}
        )

    async def row_page(
        self, file_id: UUID, status: RowStatus, after: int | None, before: int | None, limit: int
    ) -> RowPage:
        backwards = before is not None and after is None
        cursor = before if backwards else after
        comparison = "<" if backwards else ">"
        order = "DESC" if backwards else "ASC"
        rows = list(
            await self._connection.execute(
                text(
                    f"""SELECT row_number, status, parsed, error_code FROM import_rows
                        WHERE import_file_id = :file AND status = :status
                          AND (CAST(:cursor AS integer) IS NULL
                               OR row_number {comparison} :cursor)
                        ORDER BY row_number {order} LIMIT :limit"""  # noqa: S608
                ),
                {"file": file_id, "status": status.value, "cursor": cursor, "limit": limit + 1},
            )
        )
        more = len(rows) > limit
        rows = rows[:limit]
        if backwards:
            rows.reverse()
        page = [
            ImportRow(row.row_number, RowStatus(row.status), dict(row.parsed), row.error_code)
            for row in rows
        ]
        if backwards:
            return RowPage(page, has_previous=more, has_next=True)
        return RowPage(page, has_previous=cursor is not None, has_next=more)

    async def row_counts(self, file_id: UUID) -> dict[RowStatus, int]:
        rows = await self._connection.execute(
            text(
                """SELECT status, count(*) AS total FROM import_rows
                   WHERE import_file_id = :file GROUP BY status"""
            ),
            {"file": file_id},
        )
        counts = dict.fromkeys(RowStatus, 0)
        counts.update({RowStatus(row.status): row.total for row in rows})
        return counts

    async def live_fingerprints(self, bank_account_id: UUID, candidates: list[str]) -> set[str]:
        if not candidates:
            return set()
        rows = await self._connection.execute(
            text(
                """SELECT fingerprint FROM bank_movements
                   WHERE bank_account_id = :account AND voided_at IS NULL
                     AND fingerprint = ANY(:candidates)"""
            ),
            {"account": bank_account_id, "candidates": candidates},
        )
        return set(rows.scalars())

    async def enqueue(
        self,
        organization_id: UUID,
        kind: str,
        payload: Mapping[str, str],
        created_by: UUID,
        now: datetime,
    ) -> UUID:
        job_id = uuid7()
        await enqueue(
            self._connection,
            job_id=job_id,
            kind=kind,
            now=now,
            organization_id=organization_id,
            payload=payload,
            dedup_key=f"{kind}:{payload['import_file_id']}",
            created_by=created_by,
        )
        return job_id


class SqlImportTransactions:
    def __init__(
        self,
        engine: AsyncEngine,
        audit_factory: Callable[[AsyncConnection], AuditRecorder],
        periods_factory: Callable[[AsyncConnection], PeriodQueries],
    ) -> None:
        self._engine = engine
        self._audit_factory = audit_factory
        self._periods_factory = periods_factory

    def store(self, connection: AsyncConnection) -> SqlImportStore:
        return SqlImportStore(
            connection, self._audit_factory(connection), self._periods_factory(connection)
        )

    @asynccontextmanager
    async def organization(self, organization_id: UUID) -> AsyncIterator[SqlImportStore]:
        async with organization_transaction(self._engine, organization_id) as connection:
            yield self.store(connection)
