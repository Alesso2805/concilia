from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class AuditAction(StrEnum):
    ORGANIZATION_CREATED = "organization.created"
    INVITATION_ACCEPTED = "invitation.accepted"


ALLOWED_METADATA_KEYS = frozenset({"source", "roles"})


class AuditMetadataError(ValueError):
    pass


@dataclass(frozen=True)
class AuditEvent:
    id: UUID
    organization_id: UUID
    actor_user_id: UUID | None
    action: AuditAction
    entity: str
    entity_id: UUID | None
    at: datetime
    metadata: Mapping[str, str | list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        unknown = set(self.metadata) - ALLOWED_METADATA_KEYS
        if unknown:
            raise AuditMetadataError(f"metadata keys not allowed: {sorted(unknown)}")
