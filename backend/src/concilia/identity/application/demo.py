from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid7

from concilia.audit.application.recorder import AuditAction, AuditEvent
from concilia.identity.application.ports import IdentityStore
from concilia.identity.domain.model import Role, User

DEMO_EMAIL_DOMAIN = "concilia.invalid"


@dataclass(frozen=True)
class DemoMember:
    role: str
    display_name: str


async def create_demo_organization(
    store: IdentityStore,
    organization_id: UUID,
    name: str,
    members: Sequence[DemoMember],
    expires_at: datetime,
    now: datetime,
) -> dict[str, UUID]:
    """A demo organization with one passwordless demo user per role; returns their ids."""
    await store.insert_organization(organization_id, name, now, demo_expires_at=expires_at)
    users: dict[str, UUID] = {}
    for member in members:
        user_id = uuid7()
        user = User(user_id, f"demo+{user_id}@{DEMO_EMAIL_DOMAIN}", None, member.display_name)
        await store.insert_user(user, is_demo=True, now=now)
        await store.insert_membership(organization_id, user_id, frozenset({Role(member.role)}), now)
        users[member.role] = user_id
    await store.audit.record(
        AuditEvent(
            id=uuid7(),
            organization_id=organization_id,
            actor_user_id=None,
            action=AuditAction.ORGANIZATION_CREATED,
            entity="organization",
            entity_id=organization_id,
            at=now,
            metadata={"source": "demo"},
        )
    )
    return users
