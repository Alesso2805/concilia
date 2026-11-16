from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class AuditAction(StrEnum):
    ORGANIZATION_CREATED = "organization.created"
    INVITATION_CREATED = "invitation.created"
    INVITATION_REVOKED = "invitation.revoked"
    INVITATION_ACCEPTED = "invitation.accepted"
    MEMBER_ROLES_CHANGED = "member.roles_changed"
    MEMBER_REMOVED = "member.removed"
    ORGANIZATION_SETTINGS_CHANGED = "organization.settings_changed"
    BANK_ACCOUNT_CREATED = "bank_account.created"
    BANK_ACCOUNT_UPDATED = "bank_account.updated"
    BANK_ACCOUNT_ARCHIVED = "bank_account.archived"
    IMPORT_PROFILE_CREATED = "import_profile.created"
    IMPORT_PROFILE_UPDATED = "import_profile.updated"
    IMPORT_PROFILE_ARCHIVED = "import_profile.archived"
    IMPORT_UPLOADED = "import.uploaded"
    IMPORT_DISCARDED = "import.discarded"
    IMPORT_CONFIRMED = "import.confirmed"
    IMPORT_VOIDED = "import.voided"
    RECEIVABLE_CANCELLED = "receivable.cancelled"
    ENGINE_RUN_REQUESTED = "engine_run.requested"
    DEMO_ROLE_SWITCHED = "demo.role_switched"
    MATCH_CREATED = "match.created"
    MATCH_CONFIRMED = "match.confirmed"
    MATCH_DISCARDED = "match.discarded"
    MATCH_APPROVED = "match.approved"
    MATCH_REJECTED = "match.rejected"
    MATCH_REVERTED = "match.reverted"
    PERIOD_CLOSED = "period.closed"
    PERIOD_REOPENED = "period.reopened"
    EXPORT_REQUESTED = "export.requested"
    AI_SUGGESTION_REQUESTED = "ai_suggestion.requested"


class AuditEntity(StrEnum):
    ORGANIZATION = "organization"
    USER = "user"
    INVITATION = "invitation"
    MEMBER = "member"
    BANK_ACCOUNT = "bank_account"
    IMPORT_PROFILE = "import_profile"
    IMPORT_FILE = "import_file"
    RECEIVABLE = "receivable"
    ENGINE_RUN = "engine_run"
    MATCH = "match"
    PERIOD_EVENT = "period_event"
    EXPORT = "export"
    AI_SUGGESTION = "ai_suggestion"


ALLOWED_METADATA_KEYS = frozenset({"source", "roles", "kind", "fields"})


class AuditMetadataError(ValueError):
    pass


class AuditEntityError(ValueError):
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
        if self.entity not in AuditEntity:
            raise AuditEntityError(f"unknown entity: {self.entity}")
