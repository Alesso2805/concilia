from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from concilia.reporting.application.dashboard import InvalidPeriodError, NotFoundError
from concilia.reporting.application.exports import (
    ExportExpiredError,
    ExportNotReadyError,
    ExportRequest,
    ExportRoleRequiredError,
    ExportService,
)
from concilia.shared.infrastructure.web import current_principal
from concilia.shared.kernel.ids import ClientIdError, IdConflictError
from concilia.shared.kernel.principal import Principal

CurrentPrincipal = Annotated[Principal, Depends(current_principal)]
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ExportRequestBody(BaseModel):
    id: UUID
    bank_account_id: UUID
    period: date


class ExportView(BaseModel):
    id: UUID
    job_id: UUID
    bank_account_id: UUID
    period: date
    status: Literal["queued", "running", "done", "failed"]
    error_code: str | None
    expires_at: datetime | None


def _view(request: ExportRequest) -> ExportView:
    return ExportView(
        id=request.id,
        job_id=request.id,
        bank_account_id=request.bank_account_id,
        period=request.period,
        status=request.status,
        error_code=request.error_code,
        expires_at=request.expires_at,
    )


def _forbidden() -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, "role_required")


def exports_router(service: ExportService) -> APIRouter:
    router = APIRouter(prefix="/api/app/exports", tags=["reports"])

    @router.post("", status_code=status.HTTP_201_CREATED)
    async def request_export(
        body: ExportRequestBody, principal: CurrentPrincipal, response: Response
    ) -> ExportView:
        """Queue the Excel report of one account and month (`period` is its first day) for
        analysts and reviewers. The client id is also the id of the `export_period` job to
        follow; the file can be downloaded for 24 hours once it is `done`. Idempotent on the
        client id. 403 `role_required`; 404 `not_found`; 409 `id_conflict`; 422
        `invalid_period`, `id_not_uuid7` or `id_clock_skew`.
        """
        try:
            request, created = await service.request(
                principal, body.id, body.bank_account_id, body.period
            )
        except ExportRoleRequiredError:
            raise _forbidden() from None
        except NotFoundError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found") from None
        except InvalidPeriodError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_period") from None
        except ClientIdError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, error.code) from None
        except IdConflictError:
            raise HTTPException(status.HTTP_409_CONFLICT, "id_conflict") from None
        if not created:
            response.status_code = status.HTTP_200_OK
        return _view(request)

    @router.get("/{export_id}")
    async def get_export(export_id: UUID, principal: CurrentPrincipal) -> ExportView:
        """The state of a requested export. 403 `role_required`; 404 `not_found`."""
        try:
            return _view(await service.find(principal, export_id))
        except ExportRoleRequiredError:
            raise _forbidden() from None
        except NotFoundError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found") from None

    @router.get(
        "/{export_id}/file",
        response_class=Response,
        responses={200: {"content": {XLSX: {}}, "description": "The Excel workbook"}},
    )
    async def download_export(export_id: UUID, principal: CurrentPrincipal) -> Response:
        """The workbook (Resumen, Conciliados, Pendientes, Diferencias). 403 `role_required`;
        404 `not_found`; 409 `not_ready`; 410 `expired` after 24 hours."""
        try:
            export = await service.download(principal, export_id)
        except ExportRoleRequiredError:
            raise _forbidden() from None
        except NotFoundError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found") from None
        except ExportNotReadyError:
            raise HTTPException(status.HTTP_409_CONFLICT, "not_ready") from None
        except ExportExpiredError:
            raise HTTPException(status.HTTP_410_GONE, "expired") from None
        filename = f"conciliacion-{export.period:%Y-%m}.xlsx"
        return Response(
            export.content,
            media_type=XLSX,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )

    return router
