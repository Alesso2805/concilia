from collections.abc import Callable
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from concilia.demo.application.creation import DemoLimitError, DemoService
from concilia.identity.application.sessions import IssuedSession, NotADemoError, SessionService
from concilia.shared.infrastructure.web import current_principal
from concilia.shared.kernel.principal import Principal

CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


class DemoView(BaseModel):
    organization_id: UUID


class SwitchRoleRequest(BaseModel):
    role: Literal["admin", "analyst", "reviewer"]


class SwitchedView(BaseModel):
    role: Literal["admin", "analyst", "reviewer"]


def demo_router(
    service: DemoService,
    sessions: SessionService,
    set_session_cookies: Callable[[Response, IssuedSession], None],
) -> APIRouter:
    router = APIRouter(prefix="/api/public", tags=["demo"])

    @router.post("/demo", status_code=status.HTTP_201_CREATED)
    async def create_demo(request: Request, response: Response) -> DemoView:
        """Create a demo organization with fictional data and sign in as its analyst.

        At most 5 per IP and 300 in total per day (429 `demo_limit`).
        """
        ip = request.client.host if request.client else "unknown"
        try:
            demo = await service.create(ip)
        except DemoLimitError:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "demo_limit") from None
        set_session_cookies(response, await sessions.start(demo.analyst_id))
        return DemoView(organization_id=demo.organization_id)

    return router


def demo_app_router(
    sessions: SessionService, set_session_cookies: Callable[[Response, IssuedSession], None]
) -> APIRouter:
    router = APIRouter(prefix="/api/app/demo", tags=["demo"])

    @router.post("/switch-role")
    async def switch_demo_role(
        body: SwitchRoleRequest, principal: CurrentPrincipal, response: Response
    ) -> SwitchedView:
        """Continue the demo as its user with another role, in a new session.

        Only inside a live demo organization and between its demo users (403 `not_a_demo`).
        """
        try:
            issued = await sessions.switch_demo_role(principal, body.role)
        except NotADemoError:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "not_a_demo") from None
        set_session_cookies(response, issued)
        return SwitchedView(role=body.role)

    return router
