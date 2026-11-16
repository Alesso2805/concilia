from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from concilia.matching.domain.inbox import (
    CreditPage,
    CreditRow,
    Decision,
    InboxCounts,
    MatchDetail,
    MatchedReceivable,
    MatchFilters,
    MatchPage,
    MatchRow,
    MatchStatus,
    PeriodSummary,
)
from concilia.shared.infrastructure.db import organization_transaction

IN_PERIOD = """b.bank_account_id = :account AND b.booked_on >= :period
               AND b.booked_on < CAST(:period AS date) + interval '1 month'"""
LIVE_CREDIT = "b.amount_cents > 0 AND b.voided_at IS NULL"
FREE = """NOT EXISTS (
              SELECT 1 FROM match_items fi JOIN match_status fs ON fs.match_id = fi.match_id
              WHERE fi.bank_movement_id = b.id
                AND fs.status IN ('proposed', 'confirmed', 'approved'))"""
AMOUNTS = """(CAST(:min_amount AS bigint) IS NULL OR {column} >= :min_amount)
             AND (CAST(:max_amount AS bigint) IS NULL OR {column} <= :max_amount)"""


def _credit(row: Any) -> CreditRow:
    return CreditRow(row.id, row.booked_on, row.description, row.operation_number, row.amount_cents)


def _filters(filters: MatchFilters) -> dict[str, Any]:
    return {
        "rule": filters.rule,
        "min_score": filters.min_score,
        "min_amount": filters.min_amount_cents,
        "max_amount": filters.max_amount_cents,
    }


def _window[T](
    rows: list[T], limit: int, backwards: bool, cursor: object
) -> tuple[list[T], bool, bool]:
    more = len(rows) > limit
    rows = rows[:limit]
    if backwards:
        rows.reverse()
        return rows, more, True
    return rows, cursor is not None, more


class SqlInboxStore:
    def __init__(self, connection: AsyncConnection) -> None:
        self._connection = connection

    async def account_exists(self, bank_account_id: UUID) -> bool:
        found = await self._connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM bank_accounts WHERE id = :id)"),
            {"id": bank_account_id},
        )
        return bool(found)

    async def periods(self, bank_account_id: UUID) -> list[PeriodSummary]:
        rows = await self._connection.execute(
            text(
                """SELECT date_trunc('month', b.booked_on)::date AS period, count(*) AS credits,
                          coalesce(bool_or(p.closed), false) AS closed
                   FROM bank_movements b
                   LEFT JOIN period_status p
                       ON p.bank_account_id = b.bank_account_id
                      AND p.period = date_trunc('month', b.booked_on)::date
                   WHERE b.bank_account_id = :account AND b.amount_cents > 0
                     AND b.voided_at IS NULL
                   GROUP BY 1 ORDER BY 1 DESC"""
            ),
            {"account": bank_account_id},
        )
        return [PeriodSummary(row.period, row.closed, row.credits) for row in rows]

    async def counts(self, bank_account_id: UUID, period: date) -> InboxCounts:
        params = {"account": bank_account_id, "period": period}
        free = await self._connection.scalar(
            text(
                f"""SELECT count(*) FROM bank_movements b
                    WHERE {IN_PERIOD} AND {LIVE_CREDIT} AND {FREE}"""  # noqa: S608
            ),
            params,
        )
        rows = await self._connection.execute(
            text(
                f"""SELECT s.status, count(*) AS total FROM match_status s
                    WHERE s.bank_account_id = :account
                      AND s.status IN ('proposed', 'confirmed', 'approved')
                      AND EXISTS (
                          SELECT 1 FROM match_items c
                          JOIN bank_movements b ON b.id = c.bank_movement_id
                          WHERE c.match_id = s.match_id AND {IN_PERIOD})
                    GROUP BY s.status"""  # noqa: S608
            ),
            params,
        )
        totals = {row.status: row.total for row in rows}
        return InboxCounts(
            free or 0,
            totals.get(MatchStatus.PROPOSED.value, 0),
            totals.get(MatchStatus.CONFIRMED.value, 0),
            totals.get(MatchStatus.APPROVED.value, 0),
        )

    async def free_credits(
        self,
        bank_account_id: UUID,
        period: date,
        filters: MatchFilters,
        after: tuple[date, UUID] | None,
        before: tuple[date, UUID] | None,
        limit: int,
    ) -> CreditPage:
        backwards = before is not None and after is None
        cursor = before if backwards else after
        comparison, order = ("<", "DESC") if backwards else (">", "ASC")
        condition = f"(b.booked_on, b.id) {comparison} (:on, :id)" if cursor else "true"
        amounts = AMOUNTS.format(column="b.amount_cents")
        rows = list(
            await self._connection.execute(
                text(
                    f"""SELECT b.id, b.booked_on, b.description, b.operation_number,
                               b.amount_cents
                        FROM bank_movements b
                        WHERE {IN_PERIOD} AND {LIVE_CREDIT} AND {FREE} AND {amounts}
                          AND {condition}
                        ORDER BY b.booked_on {order}, b.id {order} LIMIT :limit"""  # noqa: S608
                ),
                {
                    "account": bank_account_id,
                    "period": period,
                    **_filters(filters),
                    "on": cursor[0] if cursor else None,
                    "id": cursor[1] if cursor else None,
                    "limit": limit + 1,
                },
            )
        )
        page, has_previous, has_next = _window(rows, limit, backwards, cursor)
        return CreditPage([_credit(row) for row in page], has_previous, has_next)

    async def matches(
        self,
        bank_account_id: UUID,
        period: date,
        status: MatchStatus,
        filters: MatchFilters,
        after: UUID | None,
        before: UUID | None,
        limit: int,
    ) -> MatchPage:
        backwards = before is not None and after is None
        cursor = before if backwards else after
        comparison, order = ("<", "DESC") if backwards else (">", "ASC")
        condition = f"m.id {comparison} :cursor" if cursor else "true"
        amounts = AMOUNTS.format(column="cr.credits_cents")
        rows = list(
            await self._connection.execute(
                text(
                    f"""SELECT m.id, m.source, m.rule, m.score, s.status, cr.booked_on,
                               cr.description, cr.credits_cents, rc.applied_cents,
                               rc.documents, rc.customers
                        FROM matches m
                        JOIN match_status s ON s.match_id = m.id
                        CROSS JOIN LATERAL (
                            SELECT min(b.booked_on) AS booked_on,
                                   (array_agg(b.description ORDER BY b.booked_on, b.id))[1]
                                       AS description,
                                   sum(b.amount_cents)::bigint AS credits_cents
                            FROM match_items c JOIN bank_movements b ON b.id = c.bank_movement_id
                            WHERE c.match_id = m.id
                        ) cr
                        CROSS JOIN LATERAL (
                            SELECT sum(i.applied_cents)::bigint AS applied_cents,
                                   array_agg(r.doc_number ORDER BY r.doc_number_norm) AS documents,
                                   array_agg(DISTINCT r.customer_name) AS customers
                            FROM match_items i JOIN receivables r ON r.id = i.receivable_id
                            WHERE i.match_id = m.id
                        ) rc
                        WHERE m.bank_account_id = :account AND s.status = :status
                          AND EXISTS (
                              SELECT 1 FROM match_items c
                              JOIN bank_movements b ON b.id = c.bank_movement_id
                              WHERE c.match_id = m.id AND {IN_PERIOD})
                          AND (CAST(:rule AS text) IS NULL OR m.rule = :rule)
                          AND (CAST(:min_score AS integer) IS NULL OR m.score >= :min_score)
                          AND {amounts} AND {condition}
                        ORDER BY m.id {order} LIMIT :limit"""  # noqa: S608
                ),
                {
                    "account": bank_account_id,
                    "period": period,
                    "status": status.value,
                    **_filters(filters),
                    "cursor": cursor,
                    "limit": limit + 1,
                },
            )
        )
        page, has_previous, has_next = _window(rows, limit, backwards, cursor)
        return MatchPage(
            [
                MatchRow(
                    row.id,
                    row.source,
                    row.rule,
                    row.score,
                    MatchStatus(row.status),
                    row.booked_on,
                    row.description,
                    tuple(row.documents),
                    tuple(row.customers),
                    row.credits_cents,
                    row.applied_cents,
                )
                for row in page
            ],
            has_previous,
            has_next,
        )

    async def match_detail(self, match_id: UUID) -> MatchDetail | None:
        params = {"id": match_id}
        match = (
            await self._connection.execute(
                text(
                    """SELECT m.id, m.bank_account_id, m.source, m.rule, m.score, s.status,
                              m.suggested_difference_reason, m.explanation, m.created_at
                       FROM matches m JOIN match_status s ON s.match_id = m.id
                       WHERE m.id = :id"""
                ),
                params,
            )
        ).first()
        if match is None:
            return None
        credits = await self._connection.execute(
            text(
                """SELECT b.id, b.booked_on, b.description, b.operation_number, b.amount_cents
                   FROM match_items i JOIN bank_movements b ON b.id = i.bank_movement_id
                   WHERE i.match_id = :id ORDER BY b.booked_on, b.id"""
            ),
            params,
        )
        receivables = await self._connection.execute(
            text(
                """SELECT r.id, r.doc_number, r.customer_name, r.due_on, r.amount_cents,
                          i.applied_cents, rb.available_cents
                   FROM match_items i
                   JOIN receivables r ON r.id = i.receivable_id
                   JOIN receivable_balances rb ON rb.receivable_id = r.id
                   WHERE i.match_id = :id ORDER BY r.due_on, r.doc_number_norm"""
            ),
            params,
        )
        decisions = await self._connection.execute(
            text(
                """SELECT d.action, d.reason, d.difference_reason, d.difference_note,
                          u.display_name, d.decided_at
                   FROM match_decisions d JOIN users u ON u.id = d.decided_by
                   WHERE d.match_id = :id ORDER BY d.seq"""
            ),
            params,
        )
        return MatchDetail(
            match.id,
            match.bank_account_id,
            match.source,
            match.rule,
            match.score,
            MatchStatus(match.status),
            match.suggested_difference_reason,
            match.explanation,
            match.created_at,
            [_credit(row) for row in credits],
            [
                MatchedReceivable(
                    row.id,
                    row.doc_number,
                    row.customer_name,
                    row.due_on,
                    row.amount_cents,
                    row.applied_cents,
                    row.available_cents,
                )
                for row in receivables
            ],
            [
                Decision(
                    row.action,
                    row.reason,
                    row.difference_reason,
                    row.difference_note,
                    row.display_name,
                    row.decided_at,
                )
                for row in decisions
            ],
        )


class SqlInboxTransactions:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @asynccontextmanager
    async def organization(self, organization_id: UUID) -> AsyncIterator[SqlInboxStore]:
        async with organization_transaction(self._engine, organization_id) as connection:
            yield SqlInboxStore(connection)
