import asyncio
import contextlib
import signal
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from concilia.ai.application.service import LlmChooser, Replayer, SuggestionService
from concilia.ai.infrastructure.clients import LlmClients, llm_clients
from concilia.ai.infrastructure.jobs import ai_suggest_handler
from concilia.ai.infrastructure.recordings import RecordedReplayer, load_recordings
from concilia.ai.infrastructure.sql import SqlSuggestionTransactions
from concilia.audit.infrastructure.sql import SqlAuditRecorder
from concilia.imports.application.service import ImportService
from concilia.imports.infrastructure.jobs import (
    ContentReader,
    confirm_import_handler,
    parse_import_handler,
)
from concilia.imports.infrastructure.sql import SqlImportTransactions
from concilia.matching.application.runs import EngineRunService
from concilia.matching.infrastructure.jobs import run_engine_handler
from concilia.matching.infrastructure.queries import SqlMatchQueries
from concilia.matching.infrastructure.runs_sql import SqlRunTransactions
from concilia.periods.infrastructure.sql import SqlPeriodQueries
from concilia.reporting.application.exports import ExportService
from concilia.reporting.infrastructure.exports_sql import SqlExportTransactions
from concilia.reporting.infrastructure.jobs import export_period_handler
from concilia.reporting.infrastructure.xlsx import build_workbook
from concilia.shared.infrastructure.clock import SystemClock
from concilia.shared.infrastructure.db import create_engine
from concilia.shared.infrastructure.jobs import (
    Handler,
    Job,
    Runner,
    rescue_stale,
    schedule_periodic_tasks,
)
from concilia.shared.infrastructure.logging import configure_logging
from concilia.shared.infrastructure.settings import WorkerSettings
from concilia.shared.kernel.clock import Clock

SCHEDULER_INTERVAL = timedelta(minutes=1)


async def run_noop(_job: Job, _connection: AsyncConnection) -> None:
    return None


def cleanup_handler(clock: Clock) -> Handler:
    async def run_cleanup(_job: Job, connection: AsyncConnection) -> None:
        await connection.execute(text("SELECT app_cleanup(:now)"), {"now": clock.now()})

    return run_cleanup


def handlers(
    engine: AsyncEngine,
    clock: Clock,
    llm: LlmChooser | None = None,
    replayer: Replayer | None = None,
) -> dict[str, Handler]:
    transactions = SqlImportTransactions(
        engine, SqlAuditRecorder, SqlPeriodQueries, SqlMatchQueries
    )
    imports = ImportService(transactions, ContentReader(), clock)
    run_transactions = SqlRunTransactions(engine, SqlAuditRecorder, SqlPeriodQueries)
    runs = EngineRunService(run_transactions, clock)
    export_transactions = SqlExportTransactions(engine, SqlAuditRecorder)
    exports = ExportService(export_transactions, build_workbook, clock)
    suggestion_transactions = SqlSuggestionTransactions(engine, SqlAuditRecorder)
    suggestions = SuggestionService(
        suggestion_transactions,
        llm or LlmClients(real=None),
        replayer or RecordedReplayer(load_recordings()),
        clock,
    )
    return {
        "noop": run_noop,
        "cleanup": cleanup_handler(clock),
        "parse_import": parse_import_handler(engine, imports, transactions),
        "confirm_import": confirm_import_handler(imports, transactions),
        "run_engine": run_engine_handler(engine, runs, run_transactions),
        "export_period": export_period_handler(exports, export_transactions),
        "ai_suggest": ai_suggest_handler(suggestions, suggestion_transactions),
    }


async def _wait(stop: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=seconds)


async def serve(
    engine: AsyncEngine,
    clock: Clock,
    stop: asyncio.Event,
    *,
    concurrency: int,
    poll_interval_seconds: float,
    llm: LlmChooser | None = None,
) -> None:
    runner = Runner(engine, clock, handlers(engine, clock, llm))

    async def run_jobs() -> None:
        while not stop.is_set():
            if not await runner.run_once():
                await _wait(stop, poll_interval_seconds)

    async def run_scheduler() -> None:
        while not stop.is_set():
            now = clock.now()
            await schedule_periodic_tasks(engine, now)
            await rescue_stale(engine, now)
            await _wait(stop, SCHEDULER_INTERVAL.total_seconds())

    async with asyncio.TaskGroup() as group:
        for _ in range(concurrency):
            group.create_task(run_jobs())
        group.create_task(run_scheduler())


async def main() -> None:
    settings = WorkerSettings()
    configure_logging()
    engine = create_engine(settings.database_url)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for stop_signal in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(stop_signal, stop.set)
    try:
        await serve(
            engine,
            SystemClock(),
            stop,
            concurrency=settings.worker_concurrency,
            poll_interval_seconds=settings.worker_poll_interval_seconds,
            llm=llm_clients(settings),
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
