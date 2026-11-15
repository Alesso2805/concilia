from typing import Protocol

from concilia.audit.domain.events import AuditAction, AuditEvent

__all__ = ["AuditAction", "AuditEvent", "AuditRecorder"]


class AuditRecorder(Protocol):
    async def record(self, event: AuditEvent) -> None: ...
