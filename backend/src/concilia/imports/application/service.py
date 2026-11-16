import hashlib
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID, uuid7

from concilia.audit.application.recorder import AuditAction, AuditEvent, AuditRecorder
from concilia.banking.application.profile_config import (
    ProfileKind,
    StatementConfig,
    parse_config,
)
from concilia.imports.domain.cells import Cell
from concilia.imports.domain.model import FileStatus, ImportFile, ImportRow, RowPage, RowStatus
from concilia.imports.domain.statement import (
    FileError,
    RowError,
    StatementLayout,
    StatementLine,
    fingerprints,
    read_statement,
)
from concilia.periods.application.queries import PeriodQueries, period_of
from concilia.shared.kernel.clock import Clock
from concilia.shared.kernel.ids import create_or_replay, validate_client_id
from concilia.shared.kernel.principal import Principal

ANALYST = "analyst"
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_FILENAME = 255
PAGE_LIMIT = 100


class NotAllowedError(Exception):
    pass


class NotFoundError(Exception):
    pass


class WrongStateError(Exception):
    pass


class FileTooLargeError(Exception):
    pass


@dataclass(frozen=True)
class ActiveProfile:
    id: UUID
    kind: ProfileKind
    bank_account_id: UUID | None
    name: str
    config: Mapping[str, Any]


class ImportStore(Protocol):
    audit: AuditRecorder
    periods: PeriodQueries

    async def lock_organization(self, organization_id: UUID) -> None: ...

    async def active_profile(self, profile_id: UUID) -> ActiveProfile | None: ...

    async def find_file(self, file_id: UUID) -> ImportFile | None: ...

    async def file_content(self, file_id: UUID) -> bytes: ...

    async def confirmed_with_hash(self, bank_account_id: UUID, sha256: str) -> UUID | None: ...

    async def insert_file(
        self, organization_id: UUID, file: ImportFile, content: bytes
    ) -> None: ...

    async def update_file(self, file_id: UUID, **fields: object) -> None: ...

    async def replace_rows(
        self, organization_id: UUID, file_id: UUID, rows: list[ImportRow]
    ) -> None: ...

    async def delete_rows(self, file_id: UUID) -> None: ...

    async def row_page(
        self, file_id: UUID, status: RowStatus, after: int | None, before: int | None, limit: int
    ) -> RowPage: ...

    async def row_counts(self, file_id: UUID) -> dict[RowStatus, int]: ...

    async def live_fingerprints(self, bank_account_id: UUID, candidates: list[str]) -> set[str]: ...

    async def enqueue(
        self,
        organization_id: UUID,
        kind: str,
        payload: Mapping[str, str],
        created_by: UUID,
        now: datetime,
    ) -> UUID: ...


class ImportTransactions(Protocol):
    def organization(self, organization_id: UUID) -> AbstractAsyncContextManager[ImportStore]: ...


class FileReader(Protocol):
    def check(self, content: bytes, expected_format: str) -> None: ...

    def rows(self, content: bytes, config: StatementConfig) -> list[list[Cell]]: ...


type ProgressReporter = Callable[[int], Awaitable[None]]


@dataclass(frozen=True)
class Upload:
    id: UUID
    import_profile_id: UUID
    filename: str
    content: bytes


@dataclass(frozen=True)
class UploadResult:
    file: ImportFile
    job_id: UUID | None
    duplicate_of: UUID | None
    created: bool


@dataclass(frozen=True)
class FileSummary:
    file: ImportFile
    counts: dict[RowStatus, int]
    duplicate_of: UUID | None


def _organization(principal: Principal) -> UUID:
    if principal.organization_id is None or ANALYST not in principal.roles:
        raise NotAllowedError
    return principal.organization_id


def _member_organization(principal: Principal) -> UUID:
    if principal.organization_id is None:
        raise NotAllowedError
    return principal.organization_id


def _layout(config: StatementConfig) -> StatementLayout:
    columns = config.columns
    return StatementLayout(
        date=columns.date,
        description=columns.description,
        operation_number=columns.operation_number,
        amount=columns.amount,
        debit=columns.debit,
        credit=columns.credit,
        skip_rows=config.skip_rows,
        date_format=config.date_format.value,
        decimal_separator=config.decimal_separator,
        thousands_separator=config.thousands_separator,
    )


def _parsed(line: StatementLine, fingerprint: str) -> dict[str, Any]:
    return {
        "booked_on": line.booked_on.isoformat(),
        "amount_cents": line.amount_cents,
        "description": line.description,
        "operation_number": line.operation_number,
        "fingerprint": fingerprint,
    }


def _filename(raw: str) -> str:
    name = raw.replace("\\", "/").rsplit("/", 1)[-1].strip() or "archivo"
    return name[:MAX_FILENAME]


class ImportService:
    def __init__(self, transactions: ImportTransactions, reader: FileReader, clock: Clock) -> None:
        self._transactions = transactions
        self._reader = reader
        self._clock = clock

    async def upload(self, principal: Principal, upload: Upload) -> UploadResult:
        organization_id = _organization(principal)
        now = self._clock.now()
        validate_client_id(upload.id, now)
        if len(upload.content) > MAX_FILE_BYTES:
            raise FileTooLargeError
        sha256 = hashlib.sha256(upload.content).hexdigest()
        async with self._transactions.organization(organization_id) as store:
            await store.lock_organization(organization_id)
            profile = await store.active_profile(upload.import_profile_id)
            if profile is None or profile.kind != ProfileKind.BANK_STATEMENT:
                raise NotFoundError
            self._reader.check(upload.content, str(profile.config["format"]))
            job_ids: list[UUID] = []

            async def create() -> ImportFile:
                file = ImportFile(
                    upload.id,
                    profile.kind.value,
                    profile.bank_account_id,
                    profile.id,
                    {"name": profile.name, "config": dict(profile.config)},
                    _filename(upload.filename),
                    sha256,
                    len(upload.content),
                    FileStatus.UPLOADED,
                    None,
                    None,
                    principal.user_id,
                    now,
                )
                await store.insert_file(organization_id, file, upload.content)
                job_ids.append(
                    await store.enqueue(
                        organization_id,
                        "parse_import",
                        {"import_file_id": str(file.id)},
                        principal.user_id,
                        now,
                    )
                )
                await _audit(
                    store,
                    organization_id,
                    principal.user_id,
                    AuditAction.IMPORT_UPLOADED,
                    file.id,
                    now,
                )
                return file

            def same_content(existing: ImportFile) -> bool:
                return (existing.sha256, existing.import_profile_id) == (sha256, profile.id)

            file, created = await create_or_replay(
                find=lambda: store.find_file(upload.id), create=create, same_content=same_content
            )
            duplicate = (
                await store.confirmed_with_hash(file.bank_account_id, sha256)
                if file.bank_account_id is not None
                else None
            )
        return UploadResult(file, job_ids[0] if job_ids else None, duplicate, created)

    async def summary(self, principal: Principal, file_id: UUID) -> FileSummary:
        organization_id = _member_organization(principal)
        async with self._transactions.organization(organization_id) as store:
            file = await store.find_file(file_id)
            if file is None:
                raise NotFoundError
            duplicate = None
            if file.bank_account_id is not None and file.status != FileStatus.CONFIRMED:
                duplicate = await store.confirmed_with_hash(file.bank_account_id, file.sha256)
            return FileSummary(file, await store.row_counts(file_id), duplicate)

    async def rows(
        self,
        principal: Principal,
        file_id: UUID,
        status: RowStatus,
        *,
        after: int | None = None,
        before: int | None = None,
        limit: int = 50,
    ) -> RowPage:
        organization_id = _member_organization(principal)
        async with self._transactions.organization(organization_id) as store:
            if await store.find_file(file_id) is None:
                raise NotFoundError
            return await store.row_page(file_id, status, after, before, min(limit, PAGE_LIMIT))

    async def discard(self, principal: Principal, file_id: UUID) -> None:
        organization_id = _organization(principal)
        now = self._clock.now()
        async with self._transactions.organization(organization_id) as store:
            await store.lock_organization(organization_id)
            file = await store.find_file(file_id)
            if file is None:
                raise NotFoundError
            if file.status == FileStatus.DISCARDED:
                return
            if file.status not in {FileStatus.PREVIEWED, FileStatus.FAILED}:
                raise WrongStateError
            await store.delete_rows(file_id)
            await store.update_file(file_id, status=FileStatus.DISCARDED.value, discarded_at=now)
            await _audit(
                store,
                organization_id,
                principal.user_id,
                AuditAction.IMPORT_DISCARDED,
                file_id,
                now,
            )

    async def parse(
        self, organization_id: UUID, file_id: UUID, store: ImportStore, progress: ProgressReporter
    ) -> None:
        file = await store.find_file(file_id)
        if file is None or file.status not in {FileStatus.UPLOADED, FileStatus.PARSING}:
            return
        if file.bank_account_id is None:
            raise WrongStateError
        config = parse_config(ProfileKind.BANK_STATEMENT, file.profile_snapshot["config"])
        if not isinstance(config, StatementConfig):
            raise WrongStateError
        try:
            content = await store.file_content(file_id)
            lines = read_statement(self._reader.rows(content, config), _layout(config))
        except FileError as error:
            await store.update_file(file_id, status=FileStatus.FAILED.value, error_code=error.code)
            return
        await progress(40)
        rows = await self._classify(store, file.bank_account_id, lines)
        await progress(70)
        await store.replace_rows(organization_id, file_id, rows)
        await store.update_file(file_id, status=FileStatus.PREVIEWED.value, row_count=len(rows))

    async def _classify(
        self, store: ImportStore, bank_account_id: UUID, lines: list[StatementLine | RowError]
    ) -> list[ImportRow]:
        valid = [line for line in lines if isinstance(line, StatementLine)]
        prints = dict(
            zip((id(line) for line in valid), fingerprints(bank_account_id, valid), strict=True)
        )
        existing = await store.live_fingerprints(bank_account_id, list(prints.values()))
        months = {period_of(line.booked_on) for line in valid}
        closed = await store.periods.closed_periods(bank_account_id, months)
        rows = []
        for line in lines:
            if isinstance(line, RowError):
                rows.append(
                    ImportRow(
                        line.row_number, RowStatus.ERROR, {"cells": list(line.cells)}, line.code
                    )
                )
                continue
            fingerprint = prints[id(line)]
            status = (
                RowStatus.DUPLICATE
                if fingerprint in existing
                else RowStatus.CLOSED_PERIOD
                if period_of(line.booked_on) in closed
                else RowStatus.OK
            )
            rows.append(ImportRow(line.row_number, status, _parsed(line, fingerprint)))
        return rows


async def _audit(
    store: ImportStore,
    organization_id: UUID,
    actor: UUID | None,
    action: AuditAction,
    file_id: UUID,
    now: datetime,
) -> None:
    await store.audit.record(
        AuditEvent(
            id=uuid7(),
            organization_id=organization_id,
            actor_user_id=actor,
            action=action,
            entity="import_file",
            entity_id=file_id,
            at=now,
        )
    )
