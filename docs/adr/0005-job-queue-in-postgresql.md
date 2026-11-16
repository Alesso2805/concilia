# ADR-0005: Job queue and scheduler in PostgreSQL

- Status: Accepted
- Date: 2026-11-15
- Story: CN-01

## Context

Parsing and confirming imports, running the engine, calling the AI provider, building exports and periodic cleanup must run outside HTTP requests, survive restarts, and never duplicate their results. The project already runs PostgreSQL and wants no extra service.

## Decision

**A `jobs` table is the queue.** Columns, statuses and kinds are those of SPEC. Enqueuing is an `INSERT` in the same transaction as the business write that needs it, so a job exists if and only if that write committed.

**Each job runs in three separate transactions:**

1. **Claim.** The worker picks the oldest runnable job with `SELECT ... WHERE status = 'queued' AND run_after <= :now ORDER BY run_after, id LIMIT 1 FOR UPDATE SKIP LOCKED`, sets `status = 'running'`, increments `attempts` and sets `locked_at`.
2. **Work.** In its own transaction, the worker sets `app.org_id` to the job's organization ([ADR-0002](0002-multi-tenancy-with-rls.md)), takes the organization lock when the job touches guarded data, checks whether the job's result already exists, and does the work. Progress is written in short transactions on another connection.
3. **Close.** The job becomes `done`. On error it returns to `queued` with `run_after = now + 30 s × 4^(attempts − 1)` (30 s, then 2 min) if it has attempts left (maximum 3), or becomes `failed` with an `error_code`. If the job's organization no longer exists, it becomes `failed` with `organization_gone` and is not retried. If the job row itself was deleted meanwhile (demo cleanup), closing updates nothing and the worker moves on.

**Liveness and rescue.** While a job runs, the worker holds a session-level advisory lock `pg_advisory_lock(2, hashtext(:job_id::text))` on a dedicated connection. A job in `running` whose `locked_at` is more than 10 minutes old is rescued only if `pg_try_advisory_lock` on its key succeeds (the lock is released immediately): it returns to `queued`, or becomes `failed` if it has no attempts left. A slow but live job is therefore never run twice in parallel.

**At-least-once execution, idempotent results.** A job may run more than once after a crash, so every job is idempotent. Results carry the `job_id` with `UNIQUE (job_id)` (`engine_runs`, `ai_suggestions`, `exports`), and the work transaction first checks for an existing result. `confirm_import` does nothing if the file is already confirmed. Every job kind has a test that runs it twice and checks nothing is duplicated.

**Polling.** An idle worker polls every second. The worker runs two job slots concurrently by default (`WORKER_CONCURRENCY`). On `SIGTERM` it stops claiming, lets running jobs finish within the container's grace period, and leaves the rest to the rescue rule.

**Scheduler.** The worker loop checks once a minute which periodic tasks are due. The MVP has one, `cleanup`, every 15 minutes. Each run belongs to a time slot, and the slot is the deduplication key:

- slot start = the current UTC time (`Clock.now()`) rounded down to a multiple of the task's interval;
- `dedup_key = "cleanup:" + slot start in ISO 8601`;
- the job is inserted only if no `cleanup` job with that `dedup_key` exists in any status, using `INSERT ... SELECT ... WHERE NOT EXISTS (...) ON CONFLICT (kind, dedup_key) WHERE status IN ('queued', 'running') DO NOTHING`.

The partial unique index from SPEC only covers queued and running jobs. The `NOT EXISTS` check closes the gap it leaves: without it, a slot whose job already finished would be enqueued again on the next minute's check. The `ON CONFLICT` clause covers two schedulers inserting at the same moment.

Times used by the queue (`run_after`, `locked_at`, slots) come from the injected `Clock`, so tests drive them with time-machine.

## Consequences

- No broker or extra service, and enqueuing is transactional with the business data.
- RLS and the role model apply to the queue itself: the API sees only its organization's jobs.
- Execution is at-least-once, so idempotency is a requirement of every job, enforced by tests.
- Polling adds one cheap query per second per idle worker. Throughput is far below what PostgreSQL queues can handle, and well above the MVP's needs.
- The queue is about 300 lines of code to own and test (CN-03).

## Alternatives considered

- **Celery, Dramatiq or arq with Redis.** Rejected: an extra service, and enqueuing cannot share the business transaction.
- **procrastinate (PostgreSQL-based).** Rejected: its own tables, functions and roles would have to be fitted into forced RLS, per-role grants and the catalog test, and its retry model differs from the three-transaction contract above.
- **APScheduler or cron for periodic tasks.** Rejected: slot-keyed jobs in the same table give deduplication and visibility for free.
- **`LISTEN`/`NOTIFY` instead of polling.** Deferred: it lowers latency but adds a long-lived connection and reconnection logic; one-second polling is enough for now.
