from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from concilia.audit.application.log import (
    AuditAction,
    AuditEntity,
    AuditEntry,
    AuditFilters,
    AuditLogService,
    AuditorRequiredError,
    InvalidRangeError,
)
from concilia.shared.infrastructure.web import current_principal
from concilia.shared.kernel.principal import Principal

CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


class AuditEventView(BaseModel):
    id: UUID
    at: datetime
    actor_user_id: UUID | None
    actor_name: str | None
    action: AuditAction
    entity: AuditEntity
    entity_id: UUID | None
    metadata: dict[str, str | list[str]]


class AuditPageView(BaseModel):
    events: list[AuditEventView]
    has_previous: bool
    has_next: bool
    previous_cursor: str | None
    next_cursor: str | None


class AuditActorView(BaseModel):
    user_id: UUID
    display_name: str


def _view(entry: AuditEntry) -> AuditEventView:
    return AuditEventView(
        id=entry.id,
        at=entry.at,
        actor_user_id=entry.actor_user_id,
        actor_name=entry.actor_name,
        action=AuditAction(entry.action),
        entity=AuditEntity(entry.entity),
        entity_id=entry.entity_id,
        metadata=dict(entry.metadata),
    )


def _cursor(value: str | None) -> int | None:
    if value is None:
        return None
    if not value.isdigit():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_cursor")
    return int(value)


def audit_router(service: AuditLogService) -> APIRouter:
    router = APIRouter(prefix="/api/app/audit-events", tags=["audit"])

    @router.get("")
    async def list_audit_events(
        principal: CurrentPrincipal,
        actor_user_id: UUID | None = None,
        action: AuditAction | None = None,
        entity: AuditEntity | None = None,
        from_day: Annotated[date | None, Query(alias="from")] = None,
        to_day: Annotated[date | None, Query(alias="to")] = None,
        after: str | None = None,
        before: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
    ) -> AuditPageView:
        """Who did what in the organization, newest first, for any member with a role.

        `from` and `to` are Lima days, both included. Pages by keyset: pass `next_cursor` as
        `after` or `previous_cursor` as `before`. 403 `role_required`; 422 `invalid_range` or
        `invalid_cursor`.
        """
        filters = AuditFilters(actor_user_id, action, entity, from_day, to_day)
        try:
            page = await service.page(
                principal, filters, after=_cursor(after), before=_cursor(before), limit=limit
            )
        except AuditorRequiredError:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "role_required") from None
        except InvalidRangeError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_range") from None
        entries = page.entries
        return AuditPageView(
            events=[_view(entry) for entry in entries],
            has_previous=page.has_previous,
            has_next=page.has_next,
            previous_cursor=str(entries[0].seq) if entries else None,
            next_cursor=str(entries[-1].seq) if entries else None,
        )

    @router.get("/actors")
    async def list_audit_actors(principal: CurrentPrincipal) -> list[AuditActorView]:
        """Current and former members, to filter the audit log by who acted."""
        try:
            actors = await service.actors(principal)
        except AuditorRequiredError:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "role_required") from None
        return [AuditActorView(user_id=a.user_id, display_name=a.display_name) for a in actors]

    return router
