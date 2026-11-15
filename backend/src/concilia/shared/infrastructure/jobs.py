import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid7

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from concilia.shared.infrastructure.db import (
    LockNamespace,
    anonymous_transaction,
    organization_transaction,
)
from concilia.shared.kernel.clock import Clock

MAX_ATTEMPTS = 3
STALE_AFTER = timedelta(minutes=10)
FIRST_RETRY_DELAY = timedelta(seconds=30)
RETRY_BACKOFF_FACTOR = 4
PERIODIC_TASKS: Mapping[str, timedelta] = {"cleanup": timedelta(minutes=15)}
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

LOCK_SQL = text("SELECT pg_advisory_lock(:namespace, hashtext(:key))")
TRY_LOCK_SQL = text("SELECT pg_try_advisory_lock(:namespace, hashtext(:key))")
UNLOCK_SQL = text("SELECT pg_advisory_unlock(:namespace, hashtext(:key))")

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Job:
    id: UUID
    kind: str
    organization_id: UUID | None
    payload: Mapping[str, Any]
    attempts: int


class JobError(Exception):
    def __init__(self, error_code: str, *, retry: bool = True) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.retry = retry


type Handler = Callable[[Job, AsyncConnection], Awaitable[None]]


def _lock_params(job_id: UUID) -> dict[str, object]:
    return {"namespace": LockNamespace.JOB.value, "key": str(job_id)}


def retry_delay(attempts: int) -> timedelta:
    return FIRST_RETRY_DELAY * int(RETRY_BACKOFF_FACTOR ** (attempts - 1))


def slot_start(now: datetime, interval: timedelta) -> datetime:
    return EPOCH + (now - EPOCH) // interval * interval


async def enqueue(
    connection: AsyncConnection,
    *,
    job_id: UUID,
    kind: str,
    now: datetime,
    organization_id: UUID | None = None,
    payload: Mapping[str, Any] | None = None,
    dedup_key: str | None = None,
    created_by: UUID | None = None,
) -> None:
    await connection.execute(
        text(
            """
            INSERT INTO jobs (id, organization_id, kind, payload, run_after, dedup_key,
                              created_by, created_at)
            VALUES (:id, :organization_id, :kind, CAST(:payload AS jsonb), :now, :dedup_key,
                    :created_by, :now)
            """
        ),
        {
            "id": job_id,
            "organization_id": organization_id,
            "kind": kind,
            "payload": json.dumps(payload or {}),
            "now": now,
            "dedup_key": dedup_key,
            "created_by": created_by,
        },
    )


async def claim(engine: AsyncEngine, now: datetime) -> Job | None:
    async with engine.begin() as connection:
        row = (
            await connection.execute(
                text(
                    """
                    SELECT id, kind, organization_id, payload, attempts FROM jobs
                    WHERE status = 'queued' AND run_after <= :now
                    ORDER BY run_after, id
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                    """
                ),
                {"now": now},
            )
        ).first()
        if row is None:
            return None
        await connection.execute(
            text(
                """
                UPDATE jobs SET status = 'running', attempts = attempts + 1, locked_at = :now
                WHERE id = :id
                """
            ),
            {"id": row.id, "now": now},
        )
    return Job(row.id, row.kind, row.organization_id, dict(row.payload), row.attempts + 1)


async def _close(engine: AsyncEngine, job_id: UUID, assignments: str, **values: object) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(f"UPDATE jobs SET {assignments} WHERE id = :id AND status = 'running'"),  # noqa: S608
            {"id": job_id, **values},
        )


async def rescue_stale(engine: AsyncEngine, now: datetime) -> int:
    rescued = 0
    async with engine.connect() as connection:
        stale = (
            await connection.execute(
                text(
                    """
                    SELECT id, attempts FROM jobs
                    WHERE status = 'running' AND locked_at < :cutoff
                    ORDER BY locked_at
                    """
                ),
                {"cutoff": now - STALE_AFTER},
            )
        ).all()
        await connection.commit()
        for job in stale:
            if not (await connection.execute(TRY_LOCK_SQL, _lock_params(job.id))).scalar_one():
                await connection.commit()
                continue
            try:
                if job.attempts >= MAX_ATTEMPTS:
                    assignments = "status = 'failed', error_code = 'stale_lock', finished_at = :now"
                else:
                    assignments = "status = 'queued', locked_at = NULL, run_after = :now"
                await connection.execute(
                    text(
                        f"UPDATE jobs SET {assignments} "  # noqa: S608
                        "WHERE id = :id AND status = 'running' AND locked_at < :cutoff"
                    ),
                    {"id": job.id, "now": now, "cutoff": now - STALE_AFTER},
                )
            finally:
                await connection.execute(UNLOCK_SQL, _lock_params(job.id))
                await connection.commit()
            rescued += 1
    return rescued


async def schedule_periodic_tasks(engine: AsyncEngine, now: datetime) -> None:
    async with engine.begin() as connection:
        for kind, interval in PERIODIC_TASKS.items():
            await connection.execute(
                text(
                    """
                    INSERT INTO jobs (id, kind, run_after, dedup_key, created_at)
                    SELECT :id, :kind, :now, :dedup_key, :now
                    WHERE NOT EXISTS (
                        SELECT 1 FROM jobs WHERE kind = :kind AND dedup_key = :dedup_key
                    )
                    ON CONFLICT (kind, dedup_key) WHERE status IN ('queued', 'running')
                    DO NOTHING
                    """
                ),
                {
                    "id": uuid7(),
                    "kind": kind,
                    "now": now,
                    "dedup_key": f"{kind}:{slot_start(now, interval).isoformat()}",
                },
            )


class Runner:
    def __init__(self, engine: AsyncEngine, clock: Clock, handlers: Mapping[str, Handler]) -> None:
        self._engine = engine
        self._clock = clock
        self._handlers = handlers

    async def run_once(self) -> bool:
        job = await claim(self._engine, self._clock.now())
        if job is None:
            return False
        async with self._engine.connect() as liveness:
            await liveness.execute(LOCK_SQL, _lock_params(job.id))
            await liveness.commit()
            try:
                await self._execute(job)
            finally:
                await liveness.execute(UNLOCK_SQL, _lock_params(job.id))
                await liveness.commit()
        return True

    async def _execute(self, job: Job) -> None:
        try:
            await self._work(job)
        except JobError as failure:
            log.warning(
                "job_failed",
                job_id=str(job.id),
                job_kind=job.kind,
                attempt=job.attempts,
                error_code=failure.error_code,
            )
            await self._retry_or_fail(job, failure.error_code, retry=failure.retry)
        except Exception:
            log.exception(
                "job_crashed", job_id=str(job.id), job_kind=job.kind, attempt=job.attempts
            )
            await self._retry_or_fail(job, "unexpected_error", retry=True)
        else:
            await _close(
                self._engine,
                job.id,
                "status = 'done', progress = 100, finished_at = :now",
                now=self._clock.now(),
            )

    async def _work(self, job: Job) -> None:
        handler = self._handlers.get(job.kind)
        if handler is None:
            raise JobError("unknown_kind", retry=False)
        if job.organization_id is None:
            async with anonymous_transaction(self._engine) as connection:
                await handler(job, connection)
            return
        async with organization_transaction(self._engine, job.organization_id) as connection:
            exists = await connection.execute(
                text("SELECT 1 FROM organizations WHERE id = :id"), {"id": job.organization_id}
            )
            if exists.first() is None:
                raise JobError("organization_gone", retry=False)
            await handler(job, connection)

    async def _retry_or_fail(self, job: Job, error_code: str, *, retry: bool) -> None:
        now = self._clock.now()
        if retry and job.attempts < MAX_ATTEMPTS:
            await _close(
                self._engine,
                job.id,
                "status = 'queued', locked_at = NULL, run_after = :run_after, error_code = :code",
                run_after=now + retry_delay(job.attempts),
                code=error_code,
            )
        else:
            await _close(
                self._engine,
                job.id,
                "status = 'failed', error_code = :code, finished_at = :now",
                code=error_code,
                now=now,
            )
