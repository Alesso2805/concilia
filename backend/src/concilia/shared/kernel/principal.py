from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    session_id: UUID
    organization_id: UUID | None
    roles: frozenset[str]
