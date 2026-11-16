from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from concilia.banking.application.profile_config import StatementConfig
from concilia.imports.application.service import ImportService
from concilia.imports.domain.cells import Cell
from concilia.imports.domain.statement import FileError
from concilia.imports.infrastructure.readers import detect_format, read_rows
from concilia.imports.infrastructure.sql import SqlImportTransactions
from concilia.shared.infrastructure.db import organization_transaction
from concilia.shared.infrastructure.jobs import Handler, Job, JobError, report_progress


class ContentReader:
    def check(self, content: bytes, expected_format: str) -> None:
        if detect_format(content) != expected_format:
            raise FileError("wrong_format")

    def rows(self, content: bytes, config: StatementConfig) -> list[list[Cell]]:
        return read_rows(
            content,
            expected=config.format.value,
            sheet=config.sheet,
            encoding=config.encoding,
            delimiter=config.delimiter,
            skip_rows=config.skip_rows,
        )


def _file_id(job: Job) -> tuple[UUID, UUID]:
    if job.organization_id is None:
        raise JobError("missing_organization", retry=False)
    return job.organization_id, UUID(str(job.payload["import_file_id"]))


def parse_import_handler(
    engine: AsyncEngine, service: ImportService, transactions: SqlImportTransactions
) -> Handler:
    async def run(job: Job, connection: AsyncConnection) -> None:
        organization_id, file_id = _file_id(job)
        async with organization_transaction(engine, organization_id) as side:
            await side.execute(
                text(
                    """UPDATE import_files SET status = 'parsing'
                       WHERE id = :id AND status = 'uploaded'"""
                ),
                {"id": file_id},
            )

        async def progress(percent: int) -> None:
            await report_progress(engine, job.id, percent)

        await service.parse(organization_id, file_id, transactions.store(connection), progress)

    return run
