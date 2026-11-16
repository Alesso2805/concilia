import json
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from concilia.ai.application.service import (
    KIND,
    JobStatus,
    ReceivableLabel,
    StoredSuggestion,
    SuggestionDecision,
    SuggestionRequest,
)
from concilia.ai.domain.suggestions import (
    AppliedAmount,
    CreditFacts,
    OpenReceivable,
    ServerSuggestion,
)
from concilia.audit.application.recorder import AuditRecorder
from concilia.matching.application.manual import ManualStore
from concilia.shared.infrastructure.db import (
    LockNamespace,
    lock_organization,
    organization_transaction,
)
from concilia.shared.infrastructure.jobs import enqueue
from concilia.shared.kernel.ids import IdConflictError

FREE_CREDIT = """
    SELECT b.id, b.booked_on, b.amount_cents, b.description, b.description_norm
    FROM bank_movements b
    WHERE b.id = :id AND b.amount_cents > 0 AND b.voided_at IS NULL
      AND NOT EXISTS (
          SELECT 1 FROM match_items i JOIN match_status s ON s.match_id = i.match_id
          WHERE i.bank_movement_id = b.id
            AND s.status IN ('proposed', 'confirmed', 'approved'))
      AND NOT EXISTS (
          SELECT 1 FROM period_status p
          WHERE p.bank_account_id = b.bank_account_id
            AND p.period = date_trunc('month', b.booked_on)::date AND p.closed)
"""


def _suggestion_json(suggestion: ServerSuggestion) -> dict[str, Any]:
    return {
        "applied": [
            {
                "alias": item.alias,
                "receivable_id": str(item.receivable_id),
                "applied_cents": item.applied_cents,
            }
            for item in suggestion.applied
        ],
        "difference_cents": suggestion.difference_cents,
        "confidence": suggestion.confidence,
        "explanation": suggestion.explanation,
        "difference_reason": suggestion.difference_reason,
        "recomputed": suggestion.recomputed,
    }


def _suggestion(data: dict[str, Any]) -> ServerSuggestion:
    return ServerSuggestion(
        applied=[
            AppliedAmount(item["alias"], UUID(item["receivable_id"]), item["applied_cents"])
            for item in data["applied"]
        ],
        difference_cents=data["difference_cents"],
        confidence=data["confidence"],
        explanation=data["explanation"],
        difference_reason=data["difference_reason"],
        recomputed=data["recomputed"],
    )


def _decision(row: Any) -> SuggestionDecision:
    return SuggestionDecision(
        row.id,
        row.ai_suggestion_id,
        row.suggestion_index,
        row.action,
        row.reason,
        row.match_id,
        row.decided_by,
        row.decided_at,
    )


DECISION_COLUMNS = """id, ai_suggestion_id, suggestion_index, action, reason, match_id, decided_by,
                      decided_at"""


class SqlSuggestionStore:
    def __init__(self, connection: AsyncConnection, audit: AuditRecorder) -> None:
        self._connection = connection
        self.audit = audit

    async def lock_organization(self, organization_id: UUID) -> None:
        await lock_organization(self._connection, organization_id)

    async def lock_global_quota(self) -> None:
        await self._connection.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, 0)"),
            {"namespace": LockNamespace.AI_QUOTA.value},
        )

    async def is_demo(self, organization_id: UUID) -> bool:
        found = await self._connection.scalar(
            text("SELECT is_demo FROM organizations WHERE id = :id"), {"id": organization_id}
        )
        return bool(found)

    async def free_credit(self, bank_movement_id: UUID) -> CreditFacts | None:
        row = (await self._connection.execute(text(FREE_CREDIT), {"id": bank_movement_id})).first()
        if row is None:
            return None
        return CreditFacts(
            row.id, row.booked_on, row.amount_cents, row.description, row.description_norm
        )

    async def open_receivables(self) -> Sequence[OpenReceivable]:
        rows = await self._connection.execute(
            text(
                """SELECT r.id, r.doc_number, r.doc_number_norm, r.customer_name,
                          r.customer_name_norm, r.customer_tax_id, r.issued_on, r.due_on,
                          b.available_cents
                   FROM receivables r JOIN receivable_balances b ON b.receivable_id = r.id
                   WHERE r.cancelled_at IS NULL AND b.available_cents > 0"""
            )
        )
        return [
            OpenReceivable(
                row.id,
                row.doc_number,
                row.doc_number_norm,
                row.customer_name,
                row.customer_name_norm,
                row.customer_tax_id,
                row.issued_on,
                row.due_on,
                row.available_cents,
            )
            for row in rows
        ]

    async def organization_usage(self, since: datetime, until: datetime) -> int:
        found = await self._connection.scalar(
            text(
                """SELECT count(*) FROM jobs
                   WHERE kind = :kind AND created_at >= :since AND created_at < :until"""
            ),
            {"kind": KIND, "since": since, "until": until},
        )
        return int(found or 0)

    async def global_usage(self, since: datetime, until: datetime) -> int:
        found = await self._connection.scalar(
            text("SELECT app_ai_usage_today(:since, :until)"), {"since": since, "until": until}
        )
        return int(found or 0)

    async def find_request(self, request_id: UUID) -> SuggestionRequest | None:
        row = (
            await self._connection.execute(
                text(
                    """SELECT id, payload, created_by, status, error_code FROM jobs
                       WHERE id = :id AND kind = :kind"""
                ),
                {"id": request_id, "kind": KIND},
            )
        ).first()
        if row is None:
            return None
        return SuggestionRequest(
            row.id,
            UUID(row.payload["bank_movement_id"]),
            row.created_by,
            cast(JobStatus, row.status),
            row.error_code,
        )

    async def enqueue(
        self, organization_id: UUID, request: SuggestionRequest, requested_by: UUID, now: datetime
    ) -> None:
        try:
            await enqueue(
                self._connection,
                job_id=request.id,
                kind=KIND,
                now=now,
                organization_id=organization_id,
                payload={"bank_movement_id": str(request.bank_movement_id)},
                created_by=requested_by,
            )
        except IntegrityError as error:
            raise IdConflictError from error

    async def find_suggestion(self, job_id: UUID) -> StoredSuggestion | None:
        row = (
            await self._connection.execute(
                text(
                    """SELECT id, job_id, bank_movement_id, model, prompt_version, candidates,
                              response, server_applied, replayed, input_tokens, output_tokens,
                              created_by, created_at
                       FROM ai_suggestions WHERE job_id = :job"""
                ),
                {"job": job_id},
            )
        ).first()
        if row is None:
            return None
        response = row.response
        return StoredSuggestion(
            id=row.id,
            job_id=row.job_id,
            bank_movement_id=row.bank_movement_id,
            model=row.model,
            prompt_version=row.prompt_version,
            candidates={alias: UUID(value) for alias, value in row.candidates.items()},
            response=response,
            server_applied=(
                [_suggestion(item) for item in row.server_applied]
                if row.server_applied is not None
                else None
            ),
            no_match_reason=(
                response.get("no_match_reason") if isinstance(response, dict) else None
            ),
            replayed=row.replayed,
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
            created_by=row.created_by,
            created_at=row.created_at,
        )

    async def receivable_labels(self, ids: Sequence[UUID]) -> dict[UUID, ReceivableLabel]:
        if not ids:
            return {}
        rows = await self._connection.execute(
            text("SELECT id, doc_number, customer_name FROM receivables WHERE id = ANY(:ids)"),
            {"ids": list(dict.fromkeys(ids))},
        )
        return {row.id: ReceivableLabel(row.doc_number, row.customer_name) for row in rows}

    async def decisions_of(self, ai_suggestion_id: UUID) -> list[SuggestionDecision]:
        rows = await self._connection.execute(
            text(
                f"""SELECT {DECISION_COLUMNS} FROM ai_suggestion_decisions
                    WHERE ai_suggestion_id = :id ORDER BY seq"""  # noqa: S608
            ),
            {"id": ai_suggestion_id},
        )
        return [_decision(row) for row in rows]

    async def insert_suggestion(self, organization_id: UUID, suggestion: StoredSuggestion) -> None:
        await self._connection.execute(
            text(
                """INSERT INTO ai_suggestions (id, organization_id, job_id, bank_movement_id,
                                              model, prompt_version, candidates, response,
                                              server_applied, valid, replayed, input_tokens,
                                              output_tokens, created_by, created_at)
                   VALUES (:id, :org, :job, :movement, :model, :version,
                           CAST(:candidates AS jsonb), CAST(:response AS jsonb),
                           CAST(:server_applied AS jsonb), :valid, :replayed, :input_tokens,
                           :output_tokens, :created_by, :created_at)"""
            ),
            {
                "id": suggestion.id,
                "org": organization_id,
                "job": suggestion.job_id,
                "movement": suggestion.bank_movement_id,
                "model": suggestion.model,
                "version": suggestion.prompt_version,
                "candidates": json.dumps(
                    {alias: str(value) for alias, value in suggestion.candidates.items()}
                ),
                "response": json.dumps(suggestion.response),
                "server_applied": (
                    json.dumps([_suggestion_json(s) for s in suggestion.server_applied])
                    if suggestion.server_applied is not None
                    else None
                ),
                "valid": suggestion.valid,
                "replayed": suggestion.replayed,
                "input_tokens": suggestion.input_tokens,
                "output_tokens": suggestion.output_tokens,
                "created_by": suggestion.created_by,
                "created_at": suggestion.created_at,
            },
        )


class SqlSuggestionTransactions:
    def __init__(
        self, engine: AsyncEngine, audit_factory: Callable[[AsyncConnection], AuditRecorder]
    ) -> None:
        self._engine = engine
        self._audit_factory = audit_factory

    def store(self, connection: AsyncConnection) -> SqlSuggestionStore:
        return SqlSuggestionStore(connection, self._audit_factory(connection))

    @asynccontextmanager
    async def organization(self, organization_id: UUID) -> AsyncIterator[SqlSuggestionStore]:
        async with organization_transaction(self._engine, organization_id) as connection:
            yield self.store(connection)


class SqlSuggestionDecisionStore(SqlSuggestionStore):
    def __init__(
        self, connection: AsyncConnection, audit: AuditRecorder, matches: ManualStore
    ) -> None:
        super().__init__(connection, audit)
        self.matches = matches

    async def credit_account(self, bank_movement_id: UUID) -> UUID:
        found: UUID = await self._connection.scalar(
            text("SELECT bank_account_id FROM bank_movements WHERE id = :id"),
            {"id": bank_movement_id},
        )
        return found

    async def find_decision(self, decision_id: UUID) -> SuggestionDecision | None:
        row = (
            await self._connection.execute(
                text(f"SELECT {DECISION_COLUMNS} FROM ai_suggestion_decisions WHERE id = :id"),  # noqa: S608
                {"id": decision_id},
            )
        ).first()
        return _decision(row) if row else None

    async def insert_decision(self, organization_id: UUID, decision: SuggestionDecision) -> None:
        try:
            await self._connection.execute(
                text(
                    """INSERT INTO ai_suggestion_decisions (id, organization_id, ai_suggestion_id,
                                                         suggestion_index, action, reason,
                                                         match_id, decided_by, decided_at)
                       VALUES (:id, :org, :suggestion, :index, :action, :reason, :match, :by,
                               :at)"""
                ),
                {
                    "id": decision.id,
                    "org": organization_id,
                    "suggestion": decision.ai_suggestion_id,
                    "index": decision.suggestion_index,
                    "action": decision.action,
                    "reason": decision.reason,
                    "match": decision.match_id,
                    "by": decision.decided_by,
                    "at": decision.decided_at,
                },
            )
        except IntegrityError as error:
            raise IdConflictError from error


class SqlSuggestionDecisionTransactions:
    def __init__(
        self,
        engine: AsyncEngine,
        audit_factory: Callable[[AsyncConnection], AuditRecorder],
        matches_factory: Callable[[AsyncConnection], ManualStore],
    ) -> None:
        self._engine = engine
        self._audit_factory = audit_factory
        self._matches_factory = matches_factory

    @asynccontextmanager
    async def organization(
        self, organization_id: UUID
    ) -> AsyncIterator[SqlSuggestionDecisionStore]:
        async with organization_transaction(self._engine, organization_id) as connection:
            yield SqlSuggestionDecisionStore(
                connection, self._audit_factory(connection), self._matches_factory(connection)
            )
