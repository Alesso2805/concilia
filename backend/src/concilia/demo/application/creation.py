import hmac
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid7

from concilia.banking.application.demo import DemoAccount, create_demo_banking
from concilia.banking.application.profile_config import (
    DateFormat,
    FileFormat,
    StatementColumns,
    StatementConfig,
)
from concilia.banking.application.service import BankingStore
from concilia.demo.domain.dataset import IMPORTED_MONTHS, build_dataset
from concilia.demo.domain.files import STATEMENT_COLUMNS, receivables_csv, statement_csv
from concilia.identity.application.demo import DemoMember, create_demo_organization
from concilia.identity.application.ports import IdentityStore, RateLimiter
from concilia.imports.application.demo import import_confirmed
from concilia.imports.application.service import FileReader, ImportStore
from concilia.matching.application.decisions import (
    Action,
    DecisionRequest,
    DecisionStore,
    MatchDecisionService,
)
from concilia.matching.application.runs import EngineRunService, RunStore
from concilia.periods.application.closing import PeriodAction, PeriodService, PeriodStore
from concilia.shared.kernel.clock import Clock

ORGANIZATION_NAME = "Comercial Demo SAC (datos ficticios)"
MEMBERS = (
    DemoMember("analyst", "Analista de la demo"),
    DemoMember("reviewer", "Revisora de la demo"),
    DemoMember("admin", "Administrador de la demo"),
)
STATEMENT_CONFIG = StatementConfig(
    format=FileFormat.CSV,
    delimiter=";",
    date_format=DateFormat.DAY_MONTH_YEAR,
    decimal_separator=",",
    thousands_separator=".",
    columns=StatementColumns(
        date=STATEMENT_COLUMNS[0],
        description=STATEMENT_COLUMNS[1],
        operation_number=STATEMENT_COLUMNS[2],
        amount=STATEMENT_COLUMNS[3],
    ),
)
ACCOUNT = DemoAccount(
    bank="BCP",
    alias="Cuenta corriente soles",
    number_last4="4021",
    statement_profile_name="Extracto de la demo (CSV)",
    statement_config=STATEMENT_CONFIG,
    receivables_profile_name="Cobros de la demo (CSV)",
)
DAY = timedelta(days=1)
# SPEC: with DEMO_TTL_HOURS=0 (local) a demo never expires; the column is required for demos.
NEVER = datetime(9999, 12, 31, tzinfo=UTC)


class DemoLimitError(Exception):
    pass


@dataclass(frozen=True)
class DemoPolicy:
    ttl: timedelta | None
    max_per_ip_per_day: int
    max_per_day: int


@dataclass(frozen=True)
class DemoStores:
    identity: IdentityStore
    banking: BankingStore
    imports: ImportStore
    runs: RunStore
    decisions: DecisionStore
    periods: PeriodStore


class DemoTransactions(Protocol):
    def organization(self, organization_id: UUID) -> AbstractAsyncContextManager[DemoStores]: ...


@dataclass(frozen=True)
class CreatedDemo:
    organization_id: UUID
    analyst_id: UUID


class DemoService:
    def __init__(
        self,
        transactions: DemoTransactions,
        runs: EngineRunService,
        decisions: MatchDecisionService,
        periods: PeriodService,
        reader: FileReader,
        rate_limiter: RateLimiter,
        clock: Clock,
        *,
        policy: DemoPolicy,
        key_secret: bytes,
    ) -> None:
        self._transactions = transactions
        self._runs = runs
        self._decisions = decisions
        self._periods = periods
        self._reader = reader
        self._rate_limiter = rate_limiter
        self._clock = clock
        self._policy = policy
        self._key_secret = key_secret

    def _key(self, value: str) -> str:
        return hmac.new(self._key_secret, f"demo:{value}".encode(), "sha256").hexdigest()

    async def _check_limits(self, ip: str) -> None:
        now = self._clock.now()
        if await self._rate_limiter.hit(self._key(f"ip:{ip}"), DAY, now) > (
            self._policy.max_per_ip_per_day
        ):
            raise DemoLimitError
        if await self._rate_limiter.hit(self._key("all"), DAY, now) > self._policy.max_per_day:
            raise DemoLimitError

    async def create(self, ip: str) -> CreatedDemo:
        """A new demo organization with two months imported and the first one proposed by the
        engine, confirmed by its analyst, approved and closed by its reviewer; locally (no TTL) it
        never expires."""
        await self._check_limits(ip)
        now = self._clock.now()
        organization_id = uuid7()
        expires_at = now + self._policy.ttl if self._policy.ttl else NEVER
        dataset = build_dataset()
        async with self._transactions.organization(organization_id) as stores:
            await stores.identity.lock_organization(organization_id)
            users = await create_demo_organization(
                stores.identity, organization_id, ORGANIZATION_NAME, MEMBERS, expires_at, now
            )
            banking = await create_demo_banking(stores.banking, organization_id, ACCOUNT, now)
            for month in dataset.months[:IMPORTED_MONTHS]:
                label = month.period.strftime("%Y-%m")
                for profile_id, filename, content in (
                    (
                        banking.statement_profile_id,
                        f"extracto-{label}.csv",
                        statement_csv(month.movements),
                    ),
                    (
                        banking.receivables_profile_id,
                        f"cobros-{label}.csv",
                        receivables_csv(month.receivables),
                    ),
                ):
                    await import_confirmed(
                        stores.imports,
                        self._reader,
                        organization_id,
                        profile_id=profile_id,
                        filename=filename,
                        content=content,
                        actor=users["analyst"],
                        now=now,
                    )
            run = await self._runs.preload(
                organization_id, banking.account_id, dataset.months[0].period, stores.runs
            )
            for match_id, suggested in await stores.runs.proposals_of(run.id):
                for request, actor in (
                    (DecisionRequest(Action.CONFIRM, difference_reason=suggested), "analyst"),
                    (DecisionRequest(Action.APPROVE), "reviewer"),
                ):
                    await self._decisions.apply(
                        stores.decisions,
                        organization_id,
                        match_id,
                        request,
                        actor=users[actor],
                        roles=frozenset({actor}),
                        now=now,
                    )
            await self._periods.apply(
                stores.periods,
                organization_id,
                banking.account_id,
                dataset.months[0].period,
                PeriodAction.CLOSE,
                None,
                actor=users["reviewer"],
                roles=frozenset({"reviewer"}),
            )
        return CreatedDemo(organization_id, users["analyst"])
