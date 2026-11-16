from datetime import date, datetime
from uuid import UUID, uuid7

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from concilia.imports.application.receivables_flow import ExistingReceivable, ReceivableChange
from concilia.imports.domain.model import ImportRow


class SqlReceivables:
    _connection: AsyncConnection

    async def receivables_by_document(self, documents: list[str]) -> dict[str, ExistingReceivable]:
        if not documents:
            return {}
        rows = await self._connection.execute(
            text(
                """SELECT id, doc_number_norm, due_on, amount_cents,
                          cancelled_at IS NOT NULL AS cancelled
                   FROM receivables WHERE doc_number_norm = ANY(:documents)"""
            ),
            {"documents": documents},
        )
        return {
            row.doc_number_norm: ExistingReceivable(
                row.id, row.due_on, row.amount_cents, row.cancelled
            )
            for row in rows
        }

    async def insert_receivables(
        self, organization_id: UUID, file_id: UUID, rows: list[ImportRow], now: datetime
    ) -> None:
        if not rows:
            return
        await self._connection.execute(
            text(
                """INSERT INTO receivables (id, organization_id, import_file_id, customer_name,
                                            customer_name_norm, customer_tax_id, doc_number,
                                            doc_number_norm, issued_on, due_on, amount_cents,
                                            created_at, updated_at)
                   VALUES (:id, :org, :file, :customer_name, :customer_name_norm, :tax_id,
                           :doc_number, :doc_number_norm, :issued_on, :due_on, :amount, :now,
                           :now)"""
            ),
            [
                {
                    "id": uuid7(),
                    "org": organization_id,
                    "file": file_id,
                    "customer_name": row.parsed["customer_name"],
                    "customer_name_norm": row.parsed["customer_name_norm"],
                    "tax_id": row.parsed["customer_tax_id"],
                    "doc_number": row.parsed["doc_number"],
                    "doc_number_norm": row.parsed["doc_number_norm"],
                    "issued_on": date.fromisoformat(row.parsed["issued_on"]),
                    "due_on": date.fromisoformat(row.parsed["due_on"]),
                    "amount": row.parsed["amount_cents"],
                    "now": now,
                }
                for row in rows
            ],
        )

    async def update_receivables(self, changes: list[ReceivableChange], now: datetime) -> None:
        if not changes:
            return
        await self._connection.execute(
            text(
                """UPDATE receivables
                   SET due_on = :due_on, amount_cents = :amount, updated_at = :now
                   WHERE id = :id"""
            ),
            [
                {
                    "id": change.id,
                    "due_on": change.due_on,
                    "amount": change.amount_cents,
                    "now": now,
                }
                for change in changes
            ],
        )

    async def receivable_ids_of_file(self, file_id: UUID) -> list[UUID]:
        rows = await self._connection.execute(
            text(
                """SELECT id FROM receivables
                   WHERE import_file_id = :file AND cancelled_at IS NULL ORDER BY id"""
            ),
            {"file": file_id},
        )
        return list(rows.scalars())

    async def cancel_receivables(self, ids: list[UUID], reason: str, now: datetime) -> None:
        if not ids:
            return
        await self._connection.execute(
            text(
                """UPDATE receivables SET cancelled_at = :now, cancel_reason = :reason
                   WHERE id = ANY(:ids) AND cancelled_at IS NULL"""
            ),
            {"ids": ids, "reason": reason, "now": now},
        )
