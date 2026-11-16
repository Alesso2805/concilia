from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID, uuid7

from concilia.audit.application.recorder import AuditAction, AuditEvent, AuditRecorder
from concilia.reporting.application.dashboard import (
    DashboardStore,
    InvalidPeriodError,
    NotFoundError,
    load_dashboard,
)
from concilia.reporting.domain.dashboard import month_end
from concilia.reporting.domain.workbook import MatchLine, PendingLine, PeriodReport
from concilia.shared.kernel.clock import Clock
from concilia.shared.kernel.ids import create_or_replay, validate_client_id
from concilia.shared.kernel.principal import Principal

__all__ = [
    "ExportExpiredError",
    "ExportNotReadyError",
    "ExportRequest",
    "ExportRoleRequiredError",
    "ExportService",
    "ExportStore",
    "ExportTransactions",
    "JobStatus",
    "WorkbookBuilder",
]

EXPORT_ROLES = frozenset({"analyst", "reviewer"})
EXPORT_TTL = timedelta(hours=24)
KIND = "export_period"

type JobStatus = Literal["queued", "running", "done", "failed"]


class ExportRoleRequiredError(Exception):
    pass


class ExportNotReadyError(Exception):
    pass


class ExportExpiredError(Exception):
    pass


@dataclass(frozen=True)
class ExportRequest:
    """The `export_period` job; its id is the client's id for the export."""

    id: UUID
    bank_account_id: UUID
    period: date
    requested_by: UUID | None
    status: JobStatus
    error_code: str | None
    expires_at: datetime | None


@dataclass(frozen=True)
class StoredExport:
    id: UUID
    job_id: UUID
    bank_account_id: UUID
    period: date
    content: bytes
    created_by: UUID
    created_at: datetime
    expires_at: datetime


class ExportStore(DashboardStore, Protocol):
    audit: AuditRecorder

    async def account_label(self, bank_account_id: UUID) -> str | None: ...

    async def find_request(self, request_id: UUID) -> ExportRequest | None: ...

    async def enqueue(
        self, organization_id: UUID, request: ExportRequest, requested_by: UUID, now: datetime
    ) -> None: ...

    async def find_export(self, job_id: UUID) -> StoredExport | None: ...

    async def insert_export(self, organization_id: UUID, export: StoredExport) -> None: ...

    async def match_lines(
        self, bank_account_id: UUID, start: date, end: date, statuses: Sequence[str]
    ) -> list[MatchLine]: ...

    async def pending_lines(self, bank_account_id: UUID, until: date) -> list[PendingLine]: ...


class ExportTransactions(Protocol):
    def organization(self, organization_id: UUID) -> AbstractAsyncContextManager[ExportStore]: ...


class WorkbookBuilder(Protocol):
    def __call__(self, report: PeriodReport) -> bytes: ...


def _organization(principal: Principal) -> UUID:
    if principal.organization_id is None or not principal.roles & EXPORT_ROLES:
        raise ExportRoleRequiredError
    return principal.organization_id


class ExportService:
    def __init__(
        self, transactions: ExportTransactions, build: WorkbookBuilder, clock: Clock
    ) -> None:
        self._transactions = transactions
        self._build = build
        self._clock = clock

    async def request(
        self, principal: Principal, request_id: UUID, bank_account_id: UUID, period: date
    ) -> tuple[ExportRequest, bool]:
        organization_id = _organization(principal)
        now = self._clock.now()
        validate_client_id(request_id, now)
        if period.day != 1:
            raise InvalidPeriodError
        async with self._transactions.organization(organization_id) as store:

            async def create() -> ExportRequest:
                if not await store.account_exists(bank_account_id):
                    raise NotFoundError
                request = ExportRequest(
                    request_id, bank_account_id, period, principal.user_id, "queued", None, None
                )
                await store.enqueue(organization_id, request, principal.user_id, now)
                await store.audit.record(
                    AuditEvent(
                        id=uuid7(),
                        organization_id=organization_id,
                        actor_user_id=principal.user_id,
                        action=AuditAction.EXPORT_REQUESTED,
                        entity="export",
                        entity_id=request_id,
                        at=now,
                    )
                )
                return request

            def same_content(existing: ExportRequest) -> bool:
                return (existing.bank_account_id, existing.period, existing.requested_by) == (
                    bank_account_id,
                    period,
                    principal.user_id,
                )

            return await create_or_replay(
                find=lambda: store.find_request(request_id),
                create=create,
                same_content=same_content,
            )

    async def find(self, principal: Principal, request_id: UUID) -> ExportRequest:
        organization_id = _organization(principal)
        async with self._transactions.organization(organization_id) as store:
            request = await store.find_request(request_id)
        if request is None:
            raise NotFoundError
        return request

    async def download(self, principal: Principal, request_id: UUID) -> StoredExport:
        organization_id = _organization(principal)
        async with self._transactions.organization(organization_id) as store:
            request = await store.find_request(request_id)
            if request is None:
                raise NotFoundError
            export = await store.find_export(request_id)
        if export is None:
            raise ExportNotReadyError
        if export.expires_at <= self._clock.now():
            raise ExportExpiredError
        return export

    async def build(
        self, organization_id: UUID, job_id: UUID, store: ExportStore, requested_by: UUID
    ) -> None:
        """Runs in the `export_period` job; a rerun after the export was stored does nothing."""
        if await store.find_export(job_id) is not None:
            return
        request = await store.find_request(job_id)
        account = await store.account_label(request.bank_account_id) if request else None
        if request is None or account is None:
            raise NotFoundError
        now = self._clock.now()
        period = request.period
        end = month_end(period)
        dashboard = await load_dashboard(
            store, request.bank_account_id, period, self._clock.today_lima()
        )
        lines = await store.match_lines(
            request.bank_account_id, period, end, ("confirmed", "approved")
        )
        report = PeriodReport(
            account=account,
            generated_at=now,
            dashboard=dashboard,
            reconciled=[line for line in lines if line.status == "approved"],
            pending=await store.pending_lines(request.bank_account_id, dashboard.reference_date),
            differences=[line for line in lines if line.difference_cents != 0],
        )
        await store.insert_export(
            organization_id,
            StoredExport(
                id=uuid7(),
                job_id=job_id,
                bank_account_id=request.bank_account_id,
                period=period,
                content=self._build(report),
                created_by=requested_by,
                created_at=now,
                expires_at=now + EXPORT_TTL,
            ),
        )
