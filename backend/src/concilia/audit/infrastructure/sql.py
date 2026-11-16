import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from concilia.audit.domain.events import AuditEvent


class SqlAuditRecorder:
    def __init__(self, connection: AsyncConnection) -> None:
        self._connection = connection

    async def record(self, event: AuditEvent) -> None:
        await self._connection.execute(
            text(
                """
                INSERT INTO audit_events (id, organization_id, actor_user_id, action, entity,
                                          entity_id, metadata, at)
                VALUES (:id, :organization_id, :actor_user_id, :action, :entity, :entity_id,
                        CAST(:metadata AS jsonb), :at)
                """
            ),
            {
                "id": event.id,
                "organization_id": event.organization_id,
                "actor_user_id": event.actor_user_id,
                "action": event.action.value,
                "entity": event.entity,
                "entity_id": event.entity_id,
                "metadata": json.dumps(dict(event.metadata)),
                "at": event.at,
            },
        )
