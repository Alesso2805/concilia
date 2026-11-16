from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Literal

from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from concilia.audit.api.routes import audit_router
from concilia.audit.application.log import AuditLogService
from concilia.audit.infrastructure.log_sql import SqlAuditLogTransactions
from concilia.audit.infrastructure.sql import SqlAuditRecorder
from concilia.banking.api.routes import banking_router
from concilia.banking.application.service import BankingService
from concilia.banking.infrastructure.sql import SqlBankingStore, SqlBankingTransactions
from concilia.demo.api.routes import demo_app_router, demo_router
from concilia.demo.application.creation import DemoPolicy, DemoService, DemoStores
from concilia.demo.application.files import DemoFilesService
from concilia.demo.infrastructure.sql import SqlDemoReadTransactions, SqlDemoTransactions
from concilia.identity.api.registration import registration_router
from concilia.identity.api.sessions import WebSecurity, session_routers
from concilia.identity.api.settings import settings_router
from concilia.identity.api.team import team_routers
from concilia.identity.application.registration import RegistrationService
from concilia.identity.application.sessions import LoginPolicy, SessionService
from concilia.identity.application.settings import SettingsService
from concilia.identity.application.team import TeamService
from concilia.identity.infrastructure.passwords import Argon2PasswordHasher
from concilia.identity.infrastructure.sql import (
    SqlIdentityStore,
    SqlIdentityTransactions,
    SqlRateLimiter,
)
from concilia.identity.infrastructure.team_sql import SqlTeamTransactions
from concilia.imports.api.receivables import receivables_router
from concilia.imports.api.routes import imports_router
from concilia.imports.application.service import ImportService
from concilia.imports.infrastructure.jobs import ContentReader
from concilia.imports.infrastructure.sql import SqlImportTransactions
from concilia.matching.api.decisions import decisions_router
from concilia.matching.api.inbox import inbox_router
from concilia.matching.api.manual import manual_router
from concilia.matching.api.routes import engine_runs_router
from concilia.matching.application.decisions import MatchDecisionService
from concilia.matching.application.inbox import InboxService
from concilia.matching.application.manual import ManualMatchService
from concilia.matching.application.runs import EngineRunService
from concilia.matching.infrastructure.decisions_sql import SqlDecisionTransactions
from concilia.matching.infrastructure.inbox_sql import SqlInboxTransactions
from concilia.matching.infrastructure.manual_sql import SqlManualTransactions
from concilia.matching.infrastructure.queries import SqlMatchQueries
from concilia.matching.infrastructure.runs_sql import SqlRunTransactions
from concilia.periods.api.routes import periods_router
from concilia.periods.application.closing import PeriodService
from concilia.periods.infrastructure.sql import SqlPeriodQueries, SqlPeriodTransactions
from concilia.reporting.api.routes import reports_router
from concilia.reporting.application.dashboard import DashboardService
from concilia.reporting.infrastructure.dashboard_sql import SqlDashboardTransactions
from concilia.shared.infrastructure.clock import SystemClock
from concilia.shared.infrastructure.db import create_engine
from concilia.shared.infrastructure.jobs_api import jobs_router
from concilia.shared.infrastructure.settings import ApiSettings
from concilia.shared.infrastructure.web import install_error_handlers
from concilia.shared.kernel.clock import Clock


class HealthResponse(BaseModel):
    status: Literal["ok"]


def _operation_id(route: APIRoute) -> str:
    return route.name


def create_app(settings: ApiSettings | None = None, clock: Clock | None = None) -> FastAPI:
    settings = settings or ApiSettings()
    clock = clock or SystemClock()
    engine = create_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        await engine.dispose()

    app = FastAPI(
        title="Concilia API",
        version="0.1.0",
        openapi_url="/api/openapi.json",
        docs_url=None,
        redoc_url=None,
        generate_unique_id_function=_operation_id,
        lifespan=lifespan,
    )
    app.state.engine = engine
    install_error_handlers(app)

    @app.get("/api/health", tags=["health"])
    async def get_health() -> HealthResponse:
        """Report that the API process is up."""
        return HealthResponse(status="ok")

    transactions = SqlIdentityTransactions(engine, SqlAuditRecorder)
    hasher = Argon2PasswordHasher()
    sessions = SessionService(
        transactions,
        hasher,
        SqlRateLimiter(engine),
        clock,
        policy=LoginPolicy(
            window=timedelta(minutes=settings.login_window_minutes),
            max_per_email=settings.login_max_per_email,
            max_per_ip=settings.login_max_per_ip,
        ),
        key_secret=settings.rate_limit_secret.get_secret_value().encode(),
    )
    routers = session_routers(
        sessions,
        WebSecurity(settings.public_origin, settings.csrf_secret.get_secret_value().encode()),
    )
    app.include_router(routers.public)
    app.include_router(routers.app, dependencies=[Depends(routers.authenticate)])
    app.include_router(
        registration_router(
            RegistrationService(transactions, hasher, clock),
            enabled=settings.registration_enabled,
        ),
        dependencies=[Depends(routers.require_same_origin)],
    )
    team_app, team_public = team_routers(
        TeamService(SqlTeamTransactions(engine, SqlAuditRecorder), hasher, clock),
        sessions,
        routers.set_session_cookies,
    )
    app.include_router(team_public, dependencies=[Depends(routers.require_same_origin)])
    authenticated = [Depends(routers.authenticate)]
    app.include_router(team_app, dependencies=authenticated)
    app.include_router(
        settings_router(SettingsService(transactions, clock)), dependencies=authenticated
    )
    app.include_router(
        banking_router(BankingService(SqlBankingTransactions(engine, SqlAuditRecorder), clock)),
        dependencies=authenticated,
    )
    import_transactions = SqlImportTransactions(
        engine, SqlAuditRecorder, SqlPeriodQueries, SqlMatchQueries
    )
    imports = ImportService(import_transactions, ContentReader(), clock)
    app.include_router(imports_router(imports), dependencies=authenticated)
    app.include_router(receivables_router(imports), dependencies=authenticated)
    run_transactions = SqlRunTransactions(engine, SqlAuditRecorder, SqlPeriodQueries)
    runs = EngineRunService(run_transactions, clock)
    app.include_router(engine_runs_router(runs), dependencies=authenticated)

    decision_transactions = SqlDecisionTransactions(engine, SqlAuditRecorder)
    decisions = MatchDecisionService(decision_transactions, clock)
    period_transactions = SqlPeriodTransactions(engine, SqlAuditRecorder, SqlMatchQueries)
    periods = PeriodService(period_transactions, clock)

    def demo_stores(connection: AsyncConnection) -> DemoStores:
        return DemoStores(
            SqlIdentityStore(connection, SqlAuditRecorder(connection)),
            SqlBankingStore(connection, SqlAuditRecorder(connection)),
            import_transactions.store(connection),
            run_transactions.store(connection),
            decision_transactions.store(connection),
            period_transactions.store(connection),
        )

    demo = DemoService(
        SqlDemoTransactions(engine, demo_stores),
        runs,
        decisions,
        periods,
        ContentReader(),
        SqlRateLimiter(engine),
        clock,
        policy=DemoPolicy(
            ttl=timedelta(hours=settings.demo_ttl_hours) if settings.demo_ttl_hours else None,
            max_per_ip_per_day=settings.demo_max_per_ip_per_day,
            max_per_day=settings.demo_max_per_day,
        ),
        key_secret=settings.rate_limit_secret.get_secret_value().encode(),
    )
    app.include_router(
        demo_router(demo, sessions, routers.set_session_cookies),
        dependencies=[Depends(routers.require_same_origin)],
    )
    inbox = InboxService(SqlInboxTransactions(engine))
    app.include_router(inbox_router(inbox), dependencies=authenticated)
    app.include_router(decisions_router(decisions), dependencies=authenticated)
    app.include_router(periods_router(periods), dependencies=authenticated)
    manual = ManualMatchService(SqlManualTransactions(engine, SqlAuditRecorder), decisions, clock)
    app.include_router(manual_router(manual), dependencies=authenticated)
    app.include_router(
        demo_app_router(
            sessions,
            routers.set_session_cookies,
            DemoFilesService(SqlDemoReadTransactions(engine)),
        ),
        dependencies=authenticated,
    )
    app.include_router(
        audit_router(AuditLogService(SqlAuditLogTransactions(engine))), dependencies=authenticated
    )
    app.include_router(
        reports_router(DashboardService(SqlDashboardTransactions(engine), clock)),
        dependencies=authenticated,
    )
    app.include_router(jobs_router(engine), dependencies=authenticated)
    return app
