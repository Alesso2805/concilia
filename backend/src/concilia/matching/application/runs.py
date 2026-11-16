from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from uuid import UUID, uuid7

from concilia.audit.application.recorder import AuditAction, AuditEvent, AuditRecorder
from concilia.matching.domain.engine import RULES_VERSION, run_engine
from concilia.matching.domain.model import EngineInput, Proposal
from concilia.matching.domain.runs import EngineRun
from concilia.periods.application.queries import PeriodQueries
from concilia.shared.kernel.clock import Clock
from concilia.shared.kernel.ids import create_or_replay, validate_client_id
from concilia.shared.kernel.principal import Principal

ANALYST = "analyst"


class NotAllowedError(Exception):
    pass


class NotFoundError(Exception):
    pass


class InvalidPeriodError(Exception):
    pass


class ClosedPeriodError(Exception):
    pass


class RunInProgressError(Exception):
    pass


@dataclass(frozen=True)
class RunRequest:
    id: UUID
    bank_account_id: UUID
    period: date


class RunStore(Protocol):
    audit: AuditRecorder
    periods: PeriodQueries

    async def lock_organization(self, organization_id: UUID) -> None: ...

    async def account_is_active(self, bank_account_id: UUID) -> bool: ...

    async def find_run(self, run_id: UUID) -> EngineRun | None: ...

    async def pending_run(self, bank_account_id: UUID, period: date) -> UUID | None: ...

    async def insert_run(self, organization_id: UUID, run: EngineRun) -> None: ...

    async def enqueue(
        self, organization_id: UUID, run: EngineRun, created_by: UUID, now: datetime
    ) -> None: ...

    async def engine_input(
        self, organization_id: UUID, bank_account_id: UUID, period: date
    ) -> EngineInput: ...

    async def insert_proposals(
        self, organization_id: UUID, run: EngineRun, proposals: list[Proposal], now: datetime
    ) -> None: ...

    async def finish_run(self, run_id: UUID, proposals_count: int, now: datetime) -> None: ...


class RunTransactions(Protocol):
    def organization(self, organization_id: UUID) -> AbstractAsyncContextManager[RunStore]: ...


type ProgressReporter = Callable[[int], Awaitable[None]]


async def _no_progress(_percent: int) -> None:
    pass


def _organization(principal: Principal, *, analyst: bool) -> UUID:
    if principal.organization_id is None or (analyst and ANALYST not in principal.roles):
        raise NotAllowedError
    return principal.organization_id


class EngineRunService:
    def __init__(self, transactions: RunTransactions, clock: Clock) -> None:
        self._transactions = transactions
        self._clock = clock

    async def request(self, principal: Principal, request: RunRequest) -> tuple[EngineRun, bool]:
        organization_id = _organization(principal, analyst=True)
        now = self._clock.now()
        validate_client_id(request.id, now)
        if request.period.day != 1:
            raise InvalidPeriodError
        async with self._transactions.organization(organization_id) as store:
            await store.lock_organization(organization_id)

            async def create() -> EngineRun:
                account, period = request.bank_account_id, request.period
                if not await store.account_is_active(account):
                    raise NotFoundError
                if await store.periods.closed_periods(account, {period}):
                    raise ClosedPeriodError
                if await store.pending_run(account, period) is not None:
                    raise RunInProgressError
                run = EngineRun(
                    request.id, account, period, uuid7(), RULES_VERSION, None, now, None
                )
                await store.insert_run(organization_id, run)
                await store.enqueue(organization_id, run, principal.user_id, now)
                await store.audit.record(
                    AuditEvent(
                        id=uuid7(),
                        organization_id=organization_id,
                        actor_user_id=principal.user_id,
                        action=AuditAction.ENGINE_RUN_REQUESTED,
                        entity="engine_run",
                        entity_id=run.id,
                        at=now,
                    )
                )
                return run

            def same_content(existing: EngineRun) -> bool:
                return (existing.bank_account_id, existing.period) == (
                    request.bank_account_id,
                    request.period,
                )

            return await create_or_replay(
                find=lambda: store.find_run(request.id), create=create, same_content=same_content
            )

    async def find(self, principal: Principal, run_id: UUID) -> EngineRun:
        organization_id = _organization(principal, analyst=False)
        async with self._transactions.organization(organization_id) as store:
            run = await store.find_run(run_id)
        if run is None:
            raise NotFoundError
        return run

    async def preload(
        self, organization_id: UUID, bank_account_id: UUID, period: date, store: RunStore
    ) -> EngineRun:
        """Run the engine inside a demo's creation: the only run that has no job."""
        run = EngineRun(
            uuid7(), bank_account_id, period, None, RULES_VERSION, None, self._clock.now(), None
        )
        await store.insert_run(organization_id, run)
        await self.run(organization_id, run.id, store, _no_progress)
        return run

    async def run(
        self, organization_id: UUID, run_id: UUID, store: RunStore, progress: ProgressReporter
    ) -> None:
        await store.lock_organization(organization_id)
        run = await store.find_run(run_id)
        if run is None or run.finished_at is not None:
            return
        if await store.periods.closed_periods(run.bank_account_id, {run.period}):
            raise ClosedPeriodError
        engine_input = await store.engine_input(organization_id, run.bank_account_id, run.period)
        await progress(30)
        proposals = run_engine(engine_input)
        await progress(70)
        now = self._clock.now()
        await store.insert_proposals(organization_id, run, proposals, now)
        await store.finish_run(run.id, len(proposals), now)
