from uuid import UUID, uuid7

from concilia.audit.application.recorder import AuditAction, AuditEvent
from concilia.identity.application.ports import IdentityTransactions
from concilia.identity.domain.model import Role
from concilia.identity.domain.settings import OrganizationSettings
from concilia.shared.kernel.clock import Clock
from concilia.shared.kernel.principal import Principal


class SettingsAccessError(Exception):
    pass


def _organization(principal: Principal, *, admin: bool) -> UUID:
    if principal.organization_id is None or (admin and Role.ADMIN.value not in principal.roles):
        raise SettingsAccessError
    return principal.organization_id


class SettingsService:
    def __init__(self, transactions: IdentityTransactions, clock: Clock) -> None:
        self._transactions = transactions
        self._clock = clock

    async def get(self, principal: Principal) -> OrganizationSettings:
        organization_id = _organization(principal, admin=False)
        async with self._transactions.organization(organization_id) as store:
            settings = await store.organization_settings(organization_id)
        if settings is None:
            raise SettingsAccessError
        return settings

    async def update(self, principal: Principal, wanted: OrganizationSettings) -> None:
        organization_id = _organization(principal, admin=True)
        wanted = wanted.normalized()
        now = self._clock.now()
        async with self._transactions.organization(organization_id) as store:
            await store.lock_organization(organization_id)
            current = await store.organization_settings(organization_id)
            if current is None:
                raise SettingsAccessError
            changed = wanted.changed_fields(current)
            if not changed:
                return
            await store.update_organization_settings(organization_id, wanted)
            await store.audit.record(
                AuditEvent(
                    id=uuid7(),
                    organization_id=organization_id,
                    actor_user_id=principal.user_id,
                    action=AuditAction.ORGANIZATION_SETTINGS_CHANGED,
                    entity="organization",
                    entity_id=organization_id,
                    at=now,
                    metadata={"fields": changed},
                )
            )
