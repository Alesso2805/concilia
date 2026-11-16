import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid7

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from concilia.shared.infrastructure.jobs import (
    Handler,
    Job,
    JobError,
    Runner,
    claim,
    enqueue,
    rescue_stale,
    schedule_periodic_tasks,
)
from concilia.worker import handlers, serve
from tests.support.clock import FixedClock

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 11, 16, 15, 7, tzinfo=UTC)


@pytest.fixture
async def clock(owner_engine: AsyncEngine) -> FixedClock:
    async with owner_engine.begin() as connection:
        await connection.execute(text("DELETE FROM jobs"))
    return FixedClock(NOW)


async def _enqueue(engine: AsyncEngine, kind: str = "noop", **fields: Any) -> UUID:
    job_id = uuid7()
    async with engine.begin() as connection:
        await enqueue(connection, job_id=job_id, kind=kind, now=NOW, **fields)
    return job_id


async def _job(engine: AsyncEngine, job_id: UUID) -> Any:
    async with engine.connect() as connection:
        result = await connection.execute(text("SELECT * FROM jobs WHERE id = :id"), {"id": job_id})
        return result.one()


async def _crash(_job: Job, _connection: AsyncConnection) -> None:
    raise RuntimeError


async def test_worker_process_runs_a_noop_job(
    worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    job_id = await _enqueue(worker_engine)
    stop = asyncio.Event()

    async def stop_when_done() -> None:
        for _ in range(400):
            if (await _job(worker_engine, job_id)).status == "done":
                break
            await asyncio.sleep(0.05)
        stop.set()

    async with asyncio.timeout(20), asyncio.TaskGroup() as group:
        group.create_task(serve(worker_engine, clock, stop, concurrency=1, poll_interval_seconds=0))
        group.create_task(stop_when_done())

    job = await _job(worker_engine, job_id)
    assert (job.status, job.attempts, job.progress, job.finished_at) == ("done", 1, 100, NOW)


async def test_crashing_job_is_retried_with_backoff_and_then_fails(
    worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    job_id = await _enqueue(worker_engine)
    runner = Runner(worker_engine, clock, {"noop": _crash})

    assert await runner.run_once()
    first = await _job(worker_engine, job_id)
    assert (first.status, first.attempts, first.run_after) == (
        "queued",
        1,
        NOW + timedelta(seconds=30),
    )
    assert not await runner.run_once()

    clock.advance(timedelta(seconds=30))
    assert await runner.run_once()
    second = await _job(worker_engine, job_id)
    assert (second.attempts, second.run_after) == (2, clock.now() + timedelta(minutes=2))

    clock.advance(timedelta(minutes=2))
    assert await runner.run_once()
    last = await _job(worker_engine, job_id)
    assert (last.status, last.attempts, last.error_code) == ("failed", 3, "unexpected_error")
    assert last.finished_at == clock.now()


async def test_non_retryable_failure_fails_on_the_first_attempt(
    worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    async def reject(_job: Job, _connection: AsyncConnection) -> None:
        raise JobError("bad_payload", retry=False)

    job_id = await _enqueue(worker_engine)
    await Runner(worker_engine, clock, {"noop": reject}).run_once()

    job = await _job(worker_engine, job_id)
    assert (job.status, job.attempts, job.error_code) == ("failed", 1, "bad_payload")


async def test_unknown_kind_fails_without_retry(
    worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    job_id = await _enqueue(worker_engine)
    await Runner(worker_engine, clock, {}).run_once()

    assert (await _job(worker_engine, job_id)).error_code == "unknown_kind"


async def test_organization_job_runs_in_its_organization_context(
    owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    organization_id = uuid7()
    async with owner_engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO organizations (id, name, created_at) VALUES (:id, 'gamma', :now)"),
            {"id": organization_id, "now": NOW},
        )
    seen: list[str] = []

    async def record_context(_job: Job, connection: AsyncConnection) -> None:
        seen.append(
            (await connection.execute(text("SELECT current_setting('app.org_id')"))).scalar_one()
        )

    job_id = await _enqueue(worker_engine, "run_engine", organization_id=organization_id)
    await Runner(worker_engine, clock, {"run_engine": record_context}).run_once()

    assert seen == [str(organization_id)]
    assert (await _job(worker_engine, job_id)).status == "done"


async def _mark_running(owner_engine: AsyncEngine, job_id: UUID, attempts: int) -> None:
    async with owner_engine.begin() as connection:
        await connection.execute(
            text(
                """UPDATE jobs SET status = 'running', attempts = :attempts, locked_at = :at
                   WHERE id = :id"""
            ),
            {"id": job_id, "attempts": attempts, "at": NOW - timedelta(minutes=11)},
        )


async def test_stale_job_is_rescued_only_when_its_lock_is_free(
    owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    job_id = await _enqueue(worker_engine)
    await _mark_running(owner_engine, job_id, attempts=1)
    lock_params = {"key": str(job_id)}

    async with worker_engine.connect() as holder:
        await holder.execute(text("SELECT pg_advisory_lock(2, hashtext(:key))"), lock_params)
        await holder.commit()
        assert await rescue_stale(worker_engine, clock.now()) == 0
        assert (await _job(worker_engine, job_id)).status == "running"
        await holder.execute(text("SELECT pg_advisory_unlock(2, hashtext(:key))"), lock_params)
        await holder.commit()

    assert await rescue_stale(worker_engine, clock.now()) == 1
    job = await _job(worker_engine, job_id)
    assert (job.status, job.locked_at, job.run_after) == ("queued", None, NOW)


async def test_stale_job_without_attempts_left_fails(
    owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    job_id = await _enqueue(worker_engine)
    await _mark_running(owner_engine, job_id, attempts=3)

    await rescue_stale(worker_engine, clock.now())

    job = await _job(worker_engine, job_id)
    assert (job.status, job.error_code) == ("failed", "stale_lock")


async def test_concurrent_claims_never_take_the_same_job(
    worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    queued = {await _enqueue(worker_engine), await _enqueue(worker_engine)}

    first, second, third = await asyncio.gather(*(claim(worker_engine, NOW) for _ in range(3)))

    claimed = [job.id for job in (first, second, third) if job is not None]
    assert sorted(claimed) == sorted(queued)


async def _count(engine: AsyncEngine, kind: str) -> int:
    async with engine.connect() as connection:
        result = await connection.execute(
            text("SELECT count(*) FROM jobs WHERE kind = :kind"), {"kind": kind}
        )
        return int(result.scalar_one())


async def test_scheduler_enqueues_cleanup_once_per_slot(
    worker_engine: AsyncEngine, clock: FixedClock
) -> None:
    await schedule_periodic_tasks(worker_engine, clock.now())
    await schedule_periodic_tasks(worker_engine, clock.now())
    assert await _count(worker_engine, "cleanup") == 1

    assert await Runner(worker_engine, clock, handlers(worker_engine, clock)).run_once()
    clock.advance(timedelta(minutes=7))
    await schedule_periodic_tasks(worker_engine, clock.now())
    assert await _count(worker_engine, "cleanup") == 1

    clock.advance(timedelta(minutes=1))
    await schedule_periodic_tasks(worker_engine, clock.now())
    assert await _count(worker_engine, "cleanup") == 2


@pytest.mark.parametrize("kind", ["noop", "cleanup"])
async def test_rerunning_a_job_after_a_crash_duplicates_nothing(
    owner_engine: AsyncEngine, worker_engine: AsyncEngine, clock: FixedClock, kind: str
) -> None:
    job_id = await _enqueue(worker_engine, kind)
    runner = Runner(worker_engine, clock, handlers(worker_engine, clock))
    assert await runner.run_once()
    async with owner_engine.begin() as connection:
        await connection.execute(
            text("UPDATE jobs SET status = 'queued' WHERE id = :id"), {"id": job_id}
        )

    assert await runner.run_once()

    assert await _count(worker_engine, kind) == 1
    assert (await _job(worker_engine, job_id)).status == "done"


async def test_every_worker_handler_has_a_rerun_test(worker_engine: AsyncEngine) -> None:
    covered: set[str] = {"noop", "cleanup", "parse_import", "confirm_import"}
    registered: dict[str, Handler] = handlers(worker_engine, FixedClock(NOW))

    assert set(registered) == covered
