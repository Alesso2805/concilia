from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from concilia.shared.infrastructure.db import organization_transaction
from concilia.shared.infrastructure.web import current_org


class JobView(BaseModel):
    id: UUID
    kind: str
    status: Literal["queued", "running", "done", "failed"]
    progress: int
    error_code: str | None


def jobs_router(engine: AsyncEngine) -> APIRouter:
    router = APIRouter(prefix="/api/app/jobs", tags=["jobs"])

    @router.get("/{job_id}")
    async def get_job(
        job_id: UUID, organization_id: Annotated[UUID, Depends(current_org)]
    ) -> JobView:
        """Status and progress of a background job of the current organization."""
        async with organization_transaction(engine, organization_id) as connection:
            row = (
                await connection.execute(
                    text("SELECT id, kind, status, progress, error_code FROM jobs WHERE id = :id"),
                    {"id": job_id},
                )
            ).first()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
        return JobView(
            id=row.id,
            kind=row.kind,
            status=row.status,
            progress=row.progress,
            error_code=row.error_code,
        )

    return router
