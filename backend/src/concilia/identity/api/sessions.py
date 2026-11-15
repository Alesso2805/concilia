import hmac
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from concilia.identity.application.sessions import (
    InvalidCredentialsError,
    IssuedSession,
    NotAMemberError,
    SessionService,
    TooManyAttemptsError,
    csrf_token,
)
from concilia.identity.domain.model import SESSION_ABSOLUTE_LIMIT, OrganizationAccess
from concilia.shared.infrastructure.web import current_principal
from concilia.shared.kernel.principal import Principal

SESSION_COOKIE = "__Host-concilia_session"
XSRF_COOKIE = "__Host-XSRF-TOKEN"
XSRF_HEADER = "X-XSRF-TOKEN"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@dataclass(frozen=True)
class WebSecurity:
    public_origin: str
    csrf_secret: bytes


class LoginRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)


class ChooseOrganizationRequest(BaseModel):
    organization_id: UUID


class OrganizationView(BaseModel):
    id: UUID
    name: str
    is_demo: bool
    roles: list[str]


class LoginView(BaseModel):
    organization_id: UUID | None
    organizations: list[OrganizationView]


class SessionView(BaseModel):
    user_id: UUID
    organization_id: UUID | None
    roles: list[str]
    organizations: list[OrganizationView]


def _organizations(access: list[OrganizationAccess]) -> list[OrganizationView]:
    return [
        OrganizationView(
            id=item.organization_id,
            name=item.name,
            is_demo=item.is_demo,
            roles=sorted(role.value for role in item.roles),
        )
        for item in access
    ]


@dataclass(frozen=True)
class SessionRouters:
    public: APIRouter
    app: APIRouter
    authenticate: Callable[[Request], Awaitable[None]]


def session_routers(service: SessionService, security: WebSecurity) -> SessionRouters:
    max_age = int(SESSION_ABSOLUTE_LIMIT.total_seconds())

    def set_xsrf_cookie(response: Response, session_id: UUID) -> None:
        response.set_cookie(
            XSRF_COOKIE,
            csrf_token(security.csrf_secret, session_id),
            max_age=max_age,
            secure=True,
            samesite="lax",
        )

    def set_session_cookies(response: Response, issued: IssuedSession) -> None:
        response.set_cookie(
            SESSION_COOKIE,
            issued.token,
            max_age=max_age,
            httponly=True,
            secure=True,
            samesite="lax",
        )
        set_xsrf_cookie(response, issued.session_id)

    async def require_same_origin(request: Request) -> None:
        if (
            request.method in UNSAFE_METHODS
            and request.headers.get("origin") != security.public_origin
        ):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "origin_not_allowed")

    async def authenticate(request: Request) -> None:
        token = request.cookies.get(SESSION_COOKIE)
        principal = await service.resolve(token) if token else None
        if principal is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not_authenticated")
        if request.method in UNSAFE_METHODS:
            expected = csrf_token(security.csrf_secret, principal.session_id)
            if not hmac.compare_digest(request.headers.get(XSRF_HEADER, ""), expected):
                raise HTTPException(status.HTTP_403_FORBIDDEN, "csrf_failed")
        request.state.principal = principal

    public = APIRouter(
        prefix="/api/public", tags=["session"], dependencies=[Depends(require_same_origin)]
    )
    app = APIRouter(prefix="/api/app", tags=["session"])

    @public.post("/login")
    async def login(body: LoginRequest, request: Request, response: Response) -> LoginView:
        """Start a session with email and password."""
        ip = request.client.host if request.client else "unknown"
        try:
            issued = await service.login(body.email, body.password, ip)
        except TooManyAttemptsError as error:
            retry_after = -(-error.retry_after // timedelta(seconds=1))
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "too_many_attempts",
                headers={"Retry-After": str(retry_after)},
            ) from None
        except InvalidCredentialsError:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_credentials") from None
        set_session_cookies(response, issued)
        return LoginView(
            organization_id=issued.organization_id,
            organizations=_organizations(issued.organizations),
        )

    @app.get("/session")
    async def get_session(
        principal: Annotated[Principal, Depends(current_principal)], response: Response
    ) -> SessionView:
        """Describe the current session and the organizations of its user."""
        set_xsrf_cookie(response, principal.session_id)
        return SessionView(
            user_id=principal.user_id,
            organization_id=principal.organization_id,
            roles=sorted(principal.roles),
            organizations=_organizations(await service.organizations(principal.user_id)),
        )

    @app.post("/session/organization")
    async def choose_organization(
        body: ChooseOrganizationRequest,
        principal: Annotated[Principal, Depends(current_principal)],
        response: Response,
    ) -> LoginView:
        """Switch the session to another organization of the user, rotating the session."""
        try:
            issued = await service.choose_organization(principal, body.organization_id)
        except NotAMemberError:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "not_a_member") from None
        set_session_cookies(response, issued)
        return LoginView(
            organization_id=issued.organization_id,
            organizations=_organizations(issued.organizations),
        )

    @app.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
    async def logout(
        principal: Annotated[Principal, Depends(current_principal)], response: Response
    ) -> None:
        """End the current session."""
        await service.logout(principal)
        response.delete_cookie(SESSION_COOKIE, secure=True, httponly=True, samesite="lax")
        response.delete_cookie(XSRF_COOKIE, secure=True, samesite="lax")

    return SessionRouters(public, app, authenticate)
