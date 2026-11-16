from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from concilia.matching.application.runs import ClosedPeriodError, EngineRunService
from concilia.matching.infrastructure.runs_sql import SqlRunTransactions
from concilia.shared.infrastructure.jobs import Handler, Job, JobError, report_progress


def run_engine_handler(
    engine: AsyncEngine, service: EngineRunService, transactions: SqlRunTransactions
) -> Handler:
    async def run(job: Job, connection: AsyncConnection) -> None:
        if job.organization_id is None:
            raise JobError("missing_organization", retry=False)
        run_id = UUID(str(job.payload["engine_run_id"]))

        async def progress(percent: int) -> None:
            await report_progress(engine, job.id, percent)

        try:
            await service.run(job.organization_id, run_id, transactions.store(connection), progress)
        except ClosedPeriodError:
            raise JobError("closed_period", retry=False) from None

    return run
