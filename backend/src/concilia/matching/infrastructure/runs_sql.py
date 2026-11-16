from collections import defaultdict
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid7

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from concilia.audit.application.recorder import AuditRecorder
from concilia.matching.domain.model import (
    Credit,
    DifferenceReason,
    EngineInput,
    EnginePolicy,
    MatchKey,
    OpenReceivable,
    Proposal,
)
from concilia.matching.domain.runs import EngineRun
from concilia.periods.application.queries import PeriodQueries
from concilia.shared.infrastructure.db import lock_organization, organization_transaction
from concilia.shared.infrastructure.jobs import enqueue

RUN_COLUMNS = """id, bank_account_id, period, job_id, rules_version, proposals_count, started_at,
                 finished_at"""
IN_PERIOD = """b.bank_account_id = :account AND b.booked_on >= :period
               AND b.booked_on < CAST(:period AS date) + interval '1 month'"""


def _run(row: Any) -> EngineRun:
    return EngineRun(
        row.id,
        row.bank_account_id,
        row.period,
        row.job_id,
        row.rules_version,
        row.proposals_count,
        row.started_at,
        row.finished_at,
    )


class SqlRunStore:
    def __init__(
        self, connection: AsyncConnection, audit: AuditRecorder, periods: PeriodQueries
    ) -> None:
        self._connection = connection
        self.audit = audit
        self.periods = periods

    async def lock_organization(self, organization_id: UUID) -> None:
        await lock_organization(self._connection, organization_id)

    async def account_is_active(self, bank_account_id: UUID) -> bool:
        found = await self._connection.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM bank_accounts WHERE id = :id AND archived_at IS NULL)"
            ),
            {"id": bank_account_id},
        )
        return bool(found)

    async def find_run(self, run_id: UUID) -> EngineRun | None:
        row = (
            await self._connection.execute(
                text(f"SELECT {RUN_COLUMNS} FROM engine_runs WHERE id = :id"),  # noqa: S608
                {"id": run_id},
            )
        ).first()
        return None if row is None else _run(row)

    async def pending_run(self, bank_account_id: UUID, period: date) -> UUID | None:
        found: UUID | None = await self._connection.scalar(
            text(
                """SELECT r.id FROM engine_runs r JOIN jobs j ON j.id = r.job_id
                   WHERE r.bank_account_id = :account AND r.period = :period
                     AND j.status IN ('queued', 'running')
                   LIMIT 1"""
            ),
            {"account": bank_account_id, "period": period},
        )
        return found

    async def insert_run(self, organization_id: UUID, run: EngineRun) -> None:
        await self._connection.execute(
            text(
                """INSERT INTO engine_runs (id, organization_id, bank_account_id, period, job_id,
                                            rules_version, started_at)
                   VALUES (:id, :org, :account, :period, :job, :version, :started)"""
            ),
            {
                "id": run.id,
                "org": organization_id,
                "account": run.bank_account_id,
                "period": run.period,
                "job": run.job_id,
                "version": run.rules_version,
                "started": run.started_at,
            },
        )

    async def enqueue(
        self, organization_id: UUID, run: EngineRun, created_by: UUID, now: datetime
    ) -> None:
        if run.job_id is None:
            raise ValueError("a requested run has a job")
        await enqueue(
            self._connection,
            job_id=run.job_id,
            kind="run_engine",
            now=now,
            organization_id=organization_id,
            payload={"engine_run_id": str(run.id)},
            dedup_key=f"run_engine:{run.bank_account_id}:{run.period.isoformat()}",
            created_by=created_by,
        )

    async def engine_input(
        self, organization_id: UUID, bank_account_id: UUID, period: date
    ) -> EngineInput:
        params = {"account": bank_account_id, "period": period, "org": organization_id}
        credits = await self._connection.execute(
            text(
                f"""SELECT b.id, b.booked_on, b.amount_cents, b.description_norm, b.doc_refs
                    FROM bank_movements b
                    WHERE {IN_PERIOD} AND b.amount_cents > 0 AND b.voided_at IS NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM match_items i JOIN match_status s ON s.match_id = i.match_id
                          WHERE i.bank_movement_id = b.id
                            AND s.status IN ('proposed', 'confirmed', 'approved')
                      )"""  # noqa: S608
            ),
            params,
        )
        receivables = await self._connection.execute(
            text(
                """SELECT r.id, r.doc_number_norm, r.customer_name_norm, r.customer_tax_id,
                          r.issued_on, r.due_on, b.available_cents
                   FROM receivables r JOIN receivable_balances b ON b.receivable_id = r.id
                   WHERE r.cancelled_at IS NULL AND b.available_cents > 0"""
            ),
        )
        policy = (
            await self._connection.execute(
                text(
                    """SELECT tolerance_min_cents, tolerance_bp, detraction_rates_bp
                       FROM organizations WHERE id = :org"""
                ),
                params,
            )
        ).one()
        return EngineInput(
            period=period,
            credits=tuple(
                Credit(
                    row.id,
                    row.booked_on,
                    row.amount_cents,
                    row.description_norm,
                    tuple(row.doc_refs),
                )
                for row in credits
            ),
            receivables=tuple(
                OpenReceivable(
                    row.id,
                    row.doc_number_norm,
                    row.customer_name_norm,
                    row.customer_tax_id,
                    row.issued_on,
                    row.due_on,
                    row.available_cents,
                )
                for row in receivables
            ),
            policy=EnginePolicy(
                policy.tolerance_min_cents, policy.tolerance_bp, tuple(policy.detraction_rates_bp)
            ),
            excluded=await self._refused(params),
        )

    async def _refused(self, params: dict[str, Any]) -> frozenset[MatchKey]:
        rows = await self._connection.execute(
            text(
                f"""SELECT i.match_id, i.bank_movement_id, i.receivable_id
                    FROM match_items i JOIN match_status s ON s.match_id = i.match_id
                    WHERE s.status IN ('discarded', 'rejected', 'reverted')
                      AND s.bank_account_id = :account
                      AND EXISTS (
                          SELECT 1 FROM match_items c JOIN bank_movements b
                              ON b.id = c.bank_movement_id
                          WHERE c.match_id = i.match_id AND {IN_PERIOD}
                      )"""  # noqa: S608
            ),
            params,
        )
        credits: defaultdict[UUID, set[UUID]] = defaultdict(set)
        receivables: defaultdict[UUID, set[UUID]] = defaultdict(set)
        for row in rows:
            if row.bank_movement_id is not None:
                credits[row.match_id].add(row.bank_movement_id)
            else:
                receivables[row.match_id].add(row.receivable_id)
        return frozenset(
            MatchKey(frozenset(credits[match]), frozenset(receivables[match])) for match in credits
        )

    async def insert_proposals(
        self, organization_id: UUID, run: EngineRun, proposals: list[Proposal], now: datetime
    ) -> None:
        if not proposals:
            return
        matches: list[dict[str, Any]] = []
        items: list[dict[str, Any]] = []
        for proposal in proposals:
            match_id = uuid7()
            matches.append(
                {
                    "id": match_id,
                    "org": organization_id,
                    "account": run.bank_account_id,
                    "rule": proposal.rule.value,
                    "score": proposal.score,
                    "reason": (
                        proposal.suggested_difference_reason.value
                        if proposal.suggested_difference_reason
                        else None
                    ),
                    "explanation": proposal.explanation,
                    "run": run.id,
                    "now": now,
                }
            )
            items += [
                {
                    "id": uuid7(),
                    "org": organization_id,
                    "match": match_id,
                    "movement": credit,
                    "receivable": None,
                    "applied": None,
                }
                for credit in proposal.credit_ids
            ]
            items += [
                {
                    "id": uuid7(),
                    "org": organization_id,
                    "match": match_id,
                    "movement": None,
                    "receivable": application.receivable_id,
                    "applied": application.applied_cents,
                }
                for application in proposal.applications
            ]
        await self._connection.execute(
            text(
                """INSERT INTO matches (id, organization_id, bank_account_id, source, rule, score,
                                        suggested_difference_reason, explanation, engine_run_id,
                                        created_at)
                   VALUES (:id, :org, :account, 'engine', :rule, :score, :reason, :explanation,
                           :run, :now)"""
            ),
            matches,
        )
        await self._connection.execute(
            text(
                """INSERT INTO match_items (id, organization_id, match_id, bank_movement_id,
                                            receivable_id, applied_cents)
                   VALUES (:id, :org, :match, :movement, :receivable, :applied)"""
            ),
            items,
        )

    async def proposals_of(self, run_id: UUID) -> list[tuple[UUID, DifferenceReason | None]]:
        rows = await self._connection.execute(
            text(
                """SELECT id, suggested_difference_reason FROM matches
                   WHERE engine_run_id = :run ORDER BY id"""
            ),
            {"run": run_id},
        )
        return [
            (row.id, DifferenceReason(row.suggested_difference_reason))
            if row.suggested_difference_reason
            else (row.id, None)
            for row in rows
        ]

    async def finish_run(self, run_id: UUID, proposals_count: int, now: datetime) -> None:
        await self._connection.execute(
            text(
                """UPDATE engine_runs SET proposals_count = :count, finished_at = :now
                   WHERE id = :id"""
            ),
            {"id": run_id, "count": proposals_count, "now": now},
        )


class SqlRunTransactions:
    def __init__(
        self,
        engine: AsyncEngine,
        audit_factory: Callable[[AsyncConnection], AuditRecorder],
        periods_factory: Callable[[AsyncConnection], PeriodQueries],
    ) -> None:
        self._engine = engine
        self._audit_factory = audit_factory
        self._periods_factory = periods_factory

    def store(self, connection: AsyncConnection) -> SqlRunStore:
        return SqlRunStore(
            connection, self._audit_factory(connection), self._periods_factory(connection)
        )

    @asynccontextmanager
    async def organization(self, organization_id: UUID) -> AsyncIterator[SqlRunStore]:
        async with organization_transaction(self._engine, organization_id) as connection:
            yield self.store(connection)
