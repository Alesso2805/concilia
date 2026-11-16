from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from concilia.ai.application.llm import LlmError
from concilia.ai.application.service import AiError, SuggestionService
from concilia.ai.infrastructure.sql import SqlSuggestionTransactions
from concilia.shared.infrastructure.jobs import Handler, Job, JobError


def ai_suggest_handler(
    service: SuggestionService, transactions: SqlSuggestionTransactions
) -> Handler:
    async def run(job: Job, connection: AsyncConnection) -> None:
        if job.organization_id is None:
            raise JobError("missing_organization", retry=False)
        requested_by = await connection.scalar(
            text("SELECT created_by FROM jobs WHERE id = :id"), {"id": job.id}
        )
        if requested_by is None:
            raise JobError("missing_requester", retry=False)
        try:
            await service.suggest(
                job.organization_id, job.id, transactions.store(connection), requested_by
            )
        except LlmError as error:
            raise JobError(error.code, retry=error.retry) from None
        except AiError as error:
            raise JobError(error.code, retry=False) from None

    return run
