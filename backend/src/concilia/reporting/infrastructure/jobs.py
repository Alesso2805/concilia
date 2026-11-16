from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from concilia.reporting.application.dashboard import NotFoundError
from concilia.reporting.application.exports import ExportService
from concilia.reporting.infrastructure.exports_sql import SqlExportTransactions
from concilia.shared.infrastructure.jobs import Handler, Job, JobError


def export_period_handler(service: ExportService, transactions: SqlExportTransactions) -> Handler:
    async def run(job: Job, connection: AsyncConnection) -> None:
        if job.organization_id is None:
            raise JobError("missing_organization", retry=False)
        requested_by = await connection.scalar(
            text("SELECT created_by FROM jobs WHERE id = :id"), {"id": job.id}
        )
        if requested_by is None:
            raise JobError("missing_requester", retry=False)
        try:
            await service.build(
                job.organization_id, job.id, transactions.store(connection), requested_by
            )
        except NotFoundError:
            raise JobError("not_found", retry=False) from None

    return run
