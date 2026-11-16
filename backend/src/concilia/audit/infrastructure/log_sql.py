from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from concilia.audit.application.log import Actor, AuditEntry, AuditPage
from concilia.shared.infrastructure.db import organization_transaction


class SqlAuditLogStore:
    def __init__(self, connection: AsyncConnection) -> None:
        self._connection = connection

    async def page(
        self,
        actor_user_id: UUID | None,
        action: str | None,
        entity: str | None,
        since: datetime | None,
        until: datetime | None,
        after: int | None,
        before: int | None,
        limit: int,
    ) -> AuditPage:
        backwards = before is not None and after is None
        cursor = before if backwards else after
        comparison, order = (">", "ASC") if backwards else ("<", "DESC")
        condition = f"e.seq {comparison} :cursor" if cursor is not None else "true"
        rows = list(
            await self._connection.execute(
                text(
                    f"""SELECT e.id, e.seq, e.at, e.actor_user_id, u.display_name, e.action,
                               e.entity, e.entity_id, e.metadata
                        FROM audit_events e LEFT JOIN users u ON u.id = e.actor_user_id
                        WHERE (CAST(:actor AS uuid) IS NULL OR e.actor_user_id = :actor)
                          AND (CAST(:action AS text) IS NULL OR e.action = :action)
                          AND (CAST(:entity AS text) IS NULL OR e.entity = :entity)
                          AND (CAST(:since AS timestamptz) IS NULL OR e.at >= :since)
                          AND (CAST(:until AS timestamptz) IS NULL OR e.at < :until)
                          AND {condition}
                        ORDER BY e.seq {order} LIMIT :limit"""  # noqa: S608
                ),
                {
                    "actor": actor_user_id,
                    "action": action,
                    "entity": entity,
                    "since": since,
                    "until": until,
                    "cursor": cursor,
                    "limit": limit + 1,
                },
            )
        )
        more = len(rows) > limit
        rows = rows[:limit]
        if backwards:
            rows.reverse()
            has_previous, has_next = more, True
        else:
            has_previous, has_next = cursor is not None, more
        return AuditPage(
            [
                AuditEntry(
                    row.id,
                    row.seq,
                    row.at,
                    row.actor_user_id,
                    row.display_name,
                    row.action,
                    row.entity,
                    row.entity_id,
                    row.metadata,
                )
                for row in rows
            ],
            has_previous,
            has_next,
        )

    async def actors(self) -> list[Actor]:
        rows = await self._connection.execute(
            text(
                """SELECT m.user_id, u.display_name
                   FROM memberships m JOIN users u ON u.id = m.user_id
                   ORDER BY u.display_name, m.user_id"""
            )
        )
        return [Actor(row.user_id, row.display_name) for row in rows]


class SqlAuditLogTransactions:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @asynccontextmanager
    async def organization(self, organization_id: UUID) -> AsyncIterator[SqlAuditLogStore]:
        async with organization_transaction(self._engine, organization_id) as connection:
            yield SqlAuditLogStore(connection)
