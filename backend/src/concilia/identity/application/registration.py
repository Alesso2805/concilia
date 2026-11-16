from dataclasses import dataclass
from uuid import UUID, uuid7

from concilia.audit.application.recorder import AuditAction, AuditEvent
from concilia.identity.application.ports import (
    IdentityStore,
    IdentityTransactions,
    PasswordHasher,
)
from concilia.identity.domain.model import MIN_PASSWORD_LENGTH, Role, User, normalize_email
from concilia.shared.kernel.clock import Clock
from concilia.shared.kernel.ids import create_or_replay, validate_client_id


class PasswordTooShortError(ValueError):
    pass


class EmailTakenError(Exception):
    pass


@dataclass(frozen=True)
class Registration:
    organization_id: UUID
    organization_name: str
    display_name: str
    email: str
    password: str


@dataclass(frozen=True)
class _Existing:
    organization_name: str
    admin: User | None


class RegistrationService:
    def __init__(
        self, transactions: IdentityTransactions, hasher: PasswordHasher, clock: Clock
    ) -> None:
        self._transactions = transactions
        self._hasher = hasher
        self._clock = clock

    async def register(self, command: Registration, *, source: str) -> tuple[UUID, bool]:
        now = self._clock.now()
        organization_id = validate_client_id(command.organization_id, now)
        if len(command.password) < MIN_PASSWORD_LENGTH:
            raise PasswordTooShortError
        email = normalize_email(command.email)

        async with self._transactions.organization(organization_id) as store:
            await store.lock_organization(organization_id)

            async def find() -> _Existing | None:
                name = await store.find_organization_name(organization_id)
                if name is None:
                    return None
                user = await store.find_user_by_email(email)
                is_admin = user is not None and await store.is_admin(organization_id, user.id)
                return _Existing(name, user if is_admin else None)

            async def create() -> _Existing:
                return await self._create(store, command, email, source)

            def same_content(existing: _Existing) -> bool:
                admin = existing.admin
                return (
                    existing.organization_name == command.organization_name
                    and admin is not None
                    and admin.display_name == command.display_name
                    and admin.password_hash is not None
                    and self._hasher.verify(admin.password_hash, command.password)
                )

            _, created = await create_or_replay(find=find, create=create, same_content=same_content)
        return organization_id, created

    async def _create(
        self, store: IdentityStore, command: Registration, email: str, source: str
    ) -> _Existing:
        now = self._clock.now()
        if await store.find_user_by_email(email) is not None:
            raise EmailTakenError
        user = User(uuid7(), email, self._hasher.hash(command.password), command.display_name)
        await store.insert_user(user, is_demo=False, now=now)
        await store.insert_organization(command.organization_id, command.organization_name, now)
        await store.insert_membership(
            command.organization_id, user.id, frozenset({Role.ADMIN}), now
        )
        await store.audit.record(
            AuditEvent(
                id=uuid7(),
                organization_id=command.organization_id,
                actor_user_id=user.id,
                action=AuditAction.ORGANIZATION_CREATED,
                entity="organization",
                entity_id=command.organization_id,
                at=now,
                metadata={"source": source},
            )
        )
        return _Existing(command.organization_name, user)
