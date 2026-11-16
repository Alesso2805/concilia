from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field

from concilia.imports.application.service import (
    MAX_FILE_BYTES,
    ActiveMatchesError,
    ClosedPeriodError,
    DuplicateFileError,
    FileSummary,
    FileTooLargeError,
    ImportService,
    InvalidDocumentError,
    NotAllowedError,
    NotFoundError,
    Upload,
    WrongStateError,
)
from concilia.imports.domain.model import ImportFile, ImportRow, RowStatus
from concilia.imports.domain.statement import FileError
from concilia.shared.infrastructure.web import current_principal
from concilia.shared.kernel.cursor import InvalidCursorError, decode_cursor, encode_cursor
from concilia.shared.kernel.ids import ClientIdError, IdConflictError
from concilia.shared.kernel.principal import Principal

CurrentPrincipal = Annotated[Principal, Depends(current_principal)]

ERRORS: dict[type[Exception], tuple[int, str]] = {
    NotAllowedError: (status.HTTP_403_FORBIDDEN, "role_required"),
    NotFoundError: (status.HTTP_404_NOT_FOUND, "not_found"),
    WrongStateError: (status.HTTP_409_CONFLICT, "wrong_state"),
    IdConflictError: (status.HTTP_409_CONFLICT, "id_conflict"),
    FileTooLargeError: (status.HTTP_413_CONTENT_TOO_LARGE, "file_too_large"),
    DuplicateFileError: (status.HTTP_409_CONFLICT, "duplicate_file"),
    ClosedPeriodError: (status.HTTP_409_CONFLICT, "closed_period"),
    ActiveMatchesError: (status.HTTP_409_CONFLICT, "active_matches"),
    InvalidDocumentError: (status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_document"),
}
HANDLED: tuple[type[Exception], ...] = (ClientIdError, FileError, *ERRORS)


def http_error(error: Exception) -> HTTPException:
    if isinstance(error, ClientIdError | FileError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, error.code)
    code, detail = ERRORS[type(error)]
    return HTTPException(code, detail)


class ImportFileView(BaseModel):
    id: UUID
    kind: Literal["bank_statement", "receivables"]
    bank_account_id: UUID | None
    import_profile_id: UUID
    profile_name: str
    filename: str
    size_bytes: int
    status: Literal[
        "uploaded", "parsing", "previewed", "failed", "confirmed", "discarded", "voided"
    ]
    error_code: str | None
    row_count: int | None
    created_at: datetime
    confirmed_at: datetime | None
    discarded_at: datetime | None
    voided_at: datetime | None


class ImportSummaryView(BaseModel):
    file: ImportFileView
    counts: dict[Literal["ok", "error", "duplicate", "closed_period", "conflict"], int]
    duplicate_of: UUID | None


class UploadView(BaseModel):
    file: ImportFileView
    job_id: UUID | None
    duplicate_of: UUID | None


class StatementRowView(BaseModel):
    kind: Literal["statement"] = "statement"
    row_number: int
    status: Literal["ok", "duplicate", "closed_period"]
    booked_on: date
    amount_cents: int
    description: str
    operation_number: str | None


class ReceivableRowView(BaseModel):
    kind: Literal["receivable"] = "receivable"
    row_number: int
    status: Literal["ok", "duplicate", "conflict"]
    action: Literal["create", "update", "unchanged"] | None
    conflict: Literal["cancelled", "active_matches"] | None
    customer_name: str
    customer_tax_id: str | None
    doc_number: str
    issued_on: date
    due_on: date
    amount_cents: int
    previous_due_on: date | None
    previous_amount_cents: int | None


class ErrorRowView(BaseModel):
    row_number: int
    status: Literal["error"]
    error_code: str
    cells: list[str]


class FilePageView(BaseModel):
    files: list[ImportFileView]
    has_previous: bool
    has_next: bool
    previous_cursor: str | None
    next_cursor: str | None


class ConfirmView(BaseModel):
    job_id: UUID


class VoidRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class RowPageView(BaseModel):
    rows: list[StatementRowView | ReceivableRowView | ErrorRowView]
    has_previous: bool
    has_next: bool


def _file_view(file: ImportFile) -> ImportFileView:
    return ImportFileView(
        id=file.id,
        kind=file.kind,
        bank_account_id=file.bank_account_id,
        import_profile_id=file.import_profile_id,
        profile_name=str(file.profile_snapshot.get("name", "")),
        filename=file.filename,
        size_bytes=file.size_bytes,
        status=file.status.value,
        error_code=file.error_code,
        row_count=file.row_count,
        created_at=file.created_at,
        confirmed_at=file.confirmed_at,
        discarded_at=file.discarded_at,
        voided_at=file.voided_at,
    )


def _receivable_row_view(row: ImportRow, parsed: dict[str, Any]) -> ReceivableRowView:
    previous_due_on = parsed.get("previous_due_on")
    return ReceivableRowView(
        row_number=row.row_number,
        status=row.status.value,
        action=parsed.get("action"),
        conflict=parsed.get("conflict"),
        customer_name=parsed["customer_name"],
        customer_tax_id=parsed["customer_tax_id"],
        doc_number=parsed["doc_number"],
        issued_on=date.fromisoformat(parsed["issued_on"]),
        due_on=date.fromisoformat(parsed["due_on"]),
        amount_cents=parsed["amount_cents"],
        previous_due_on=date.fromisoformat(previous_due_on) if previous_due_on else None,
        previous_amount_cents=parsed.get("previous_amount_cents"),
    )


def _row_view(row: ImportRow) -> StatementRowView | ReceivableRowView | ErrorRowView:
    parsed: dict[str, Any] = dict(row.parsed)
    if row.status == RowStatus.ERROR:
        return ErrorRowView(
            row_number=row.row_number,
            status="error",
            error_code=row.error_code or "",
            cells=[str(cell) for cell in parsed.get("cells", [])],
        )
    if "doc_number_norm" in parsed:
        return _receivable_row_view(row, parsed)
    return StatementRowView(
        row_number=row.row_number,
        status=row.status.value,
        booked_on=date.fromisoformat(parsed["booked_on"]),
        amount_cents=parsed["amount_cents"],
        description=parsed["description"],
        operation_number=parsed.get("operation_number"),
    )


def _summary_view(summary: FileSummary) -> ImportSummaryView:
    return ImportSummaryView(
        file=_file_view(summary.file),
        counts={key.value: value for key, value in summary.counts.items()},
        duplicate_of=summary.duplicate_of,
    )


def imports_router(service: ImportService) -> APIRouter:
    router = APIRouter(prefix="/api/app/imports", tags=["imports"])

    @router.post("", status_code=status.HTTP_201_CREATED)
    async def upload_import(
        id: Annotated[UUID, Form()],
        import_profile_id: Annotated[UUID, Form()],
        file: Annotated[UploadFile, File()],
        principal: CurrentPrincipal,
        response: Response,
    ) -> UploadView:
        """Upload a bank statement or a receivables file (CSV or XLSX, up to 5 MB) and queue
        its preview.

        Analysts only; idempotent on the client-generated id. `duplicate_of` warns about a
        confirmed file of the same kind with the same content (in the same account for a
        statement).
        """
        content = await file.read(MAX_FILE_BYTES + 1)
        upload = Upload(id, import_profile_id, file.filename or "", content)
        try:
            result = await service.upload(principal, upload)
        except HANDLED as error:
            raise http_error(error) from None
        if not result.created:
            response.status_code = status.HTTP_200_OK
        return UploadView(
            file=_file_view(result.file), job_id=result.job_id, duplicate_of=result.duplicate_of
        )

    @router.get("")
    async def list_imports(
        principal: CurrentPrincipal,
        after: str | None = None,
        before: str | None = None,
        limit: Annotated[int, Query(gt=0, le=100)] = 20,
    ) -> FilePageView:
        """Imports from newest to oldest, by keyset cursor (no total, no jump to the end)."""
        try:
            page = await service.files(
                principal,
                after=decode_cursor(after) if after else None,
                before=decode_cursor(before) if before else None,
                limit=limit,
            )
        except InvalidCursorError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_cursor") from None
        except HANDLED as error:
            raise http_error(error) from None
        files = page.files
        return FilePageView(
            files=[_file_view(file) for file in files],
            has_previous=page.has_previous,
            has_next=page.has_next,
            previous_cursor=encode_cursor(files[0].created_at, files[0].id) if files else None,
            next_cursor=encode_cursor(files[-1].created_at, files[-1].id) if files else None,
        )

    @router.get("/{file_id}")
    async def get_import(file_id: UUID, principal: CurrentPrincipal) -> ImportSummaryView:
        """An import with its row counts by status."""
        try:
            return _summary_view(await service.summary(principal, file_id))
        except HANDLED as error:
            raise http_error(error) from None

    @router.get("/{file_id}/rows")
    async def list_import_rows(
        file_id: UUID,
        principal: CurrentPrincipal,
        row_status: Annotated[
            Literal["ok", "error", "duplicate", "closed_period", "conflict"],
            Query(alias="status"),
        ] = "ok",
        after: Annotated[int | None, Query(gt=0)] = None,
        before: Annotated[int | None, Query(gt=0)] = None,
        limit: Annotated[int, Query(gt=0, le=100)] = 50,
    ) -> RowPageView:
        """A page of preview rows of one status, by row number (keyset pagination)."""
        try:
            page = await service.rows(
                principal, file_id, RowStatus(row_status), after=after, before=before, limit=limit
            )
        except HANDLED as error:
            raise http_error(error) from None
        return RowPageView(
            rows=[_row_view(row) for row in page.rows],
            has_previous=page.has_previous,
            has_next=page.has_next,
        )

    @router.post("/{file_id}/discard", status_code=status.HTTP_204_NO_CONTENT)
    async def discard_import(file_id: UUID, principal: CurrentPrincipal) -> None:
        """Discard a preview without saving any movement. Analysts only."""
        try:
            await service.discard(principal, file_id)
        except HANDLED as error:
            raise http_error(error) from None

    @router.post("/{file_id}/confirm", status_code=status.HTTP_202_ACCEPTED)
    async def confirm_import(file_id: UUID, principal: CurrentPrincipal) -> ConfirmView:
        """Queue the confirmation of a preview. Analysts only.

        Repeating the request while the job is pending returns the same job.
        """
        try:
            return ConfirmView(job_id=await service.request_confirm(principal, file_id))
        except HANDLED as error:
            raise http_error(error) from None

    @router.post("/{file_id}/void", status_code=status.HTTP_204_NO_CONTENT)
    async def void_import(file_id: UUID, body: VoidRequest, principal: CurrentPrincipal) -> None:
        """Void a confirmed import. Analysts only.

        A statement voids its movements; refused if any is in a closed period or in an active
        match. A receivables import cancels the receivables it created; refused if any is in a
        proposed or confirmed match.
        """
        try:
            await service.void(principal, file_id, body.reason)
        except HANDLED as error:
            raise http_error(error) from None

    return router
