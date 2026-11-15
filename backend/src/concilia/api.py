from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Literal

from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from pydantic import BaseModel

from concilia.audit.infrastructure.sql import SqlAuditRecorder
from concilia.identity.api.registration import registration_router
from concilia.identity.api.sessions import WebSecurity, session_routers
from concilia.identity.application.registration import RegistrationService
from concilia.identity.application.sessions import LoginPolicy, SessionService
from concilia.identity.infrastructure.passwords import Argon2PasswordHasher
from concilia.identity.infrastructure.sql import SqlIdentityTransactions, SqlRateLimiter
from concilia.shared.infrastructure.clock import SystemClock
from concilia.shared.infrastructure.db import create_engine
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
    return app
