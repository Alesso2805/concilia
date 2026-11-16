from collections.abc import Callable
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from concilia.demo.application.creation import DemoLimitError, DemoService
from concilia.identity.application.sessions import IssuedSession, SessionService


class DemoView(BaseModel):
    organization_id: UUID


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
