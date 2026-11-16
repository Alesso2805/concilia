import secrets
from collections.abc import Iterable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid7

from concilia.audit.application.recorder import AuditAction, AuditEvent
from concilia.identity.application.ports import IdentityStore, PasswordHasher
from concilia.identity.application.registration import PasswordTooShortError
from concilia.identity.application.sessions import hash_token
from concilia.identity.domain.model import MIN_PASSWORD_LENGTH, Role, User, normalize_email
from concilia.identity.domain.team import (
    INVITATION_LIFETIME,
    Invitation,
    Member,
    check_email,
    ensure_an_admin_remains,
    parse_roles,
)
from concilia.shared.kernel.clock import Clock
from concilia.shared.kernel.ids import create_or_replay, validate_client_id
from concilia.shared.kernel.principal import Principal


class NotAdminError(Exception):
    pass


class NotFoundError(Exception):
    pass


class AlreadyMemberError(Exception):
    pass


class InvitationAlreadyAcceptedError(Exception):
    pass


class InvitationNotValidError(Exception):
    pass


class TeamStore(IdentityStore, Protocol):
    async def members(self) -> list[Member]: ...

    async def invitations(self) -> list[Invitation]: ...

    async def find_invitation(self, invitation_id: UUID) -> Invitation | None: ...

    async def insert_invitation(self, invitation: Invitation, token_hash: str) -> None: ...

    async def revoke_invitation(self, invitation_id: UUID, now: datetime) -> None: ...

    async def replace_roles(
        self, organization_id: UUID, user_id: UUID, roles: frozenset[Role]
    ) -> None: ...

    async def remove_member(self, organization_id: UUID, user_id: UUID, now: datetime) -> None: ...

    async def revoke_sessions(
        self, organization_id: UUID, user_id: UUID, now: datetime
    ) -> None: ...

    async def accept_invitation(
        self, token_hash: str, user_id: UUID, now: datetime, event_id: UUID
    ) -> UUID | None: ...


class TeamTransactions(Protocol):
    def anonymous(self) -> AbstractAsyncContextManager[TeamStore]: ...

    def organization(self, organization_id: UUID) -> AbstractAsyncContextManager[TeamStore]: ...


@dataclass(frozen=True)
class TeamOverview:
    members: list[Member]
    invitations: list[Invitation]


@dataclass(frozen=True)
class InviteCommand:
    id: UUID
    email: str
    roles: frozenset[str]


@dataclass(frozen=True)
class IssuedInvitation:
    invitation: Invitation
    token: str | None
    created: bool


@dataclass(frozen=True)
class NewAccount:
    token: str
    email: str
    display_name: str
    password: str


def _organization_of(principal: Principal) -> UUID:
    if principal.organization_id is None or Role.ADMIN.value not in principal.roles:
        raise NotAdminError
    return principal.organization_id


class TeamService:
    def __init__(
        self, transactions: TeamTransactions, hasher: PasswordHasher, clock: Clock
    ) -> None:
        self._transactions = transactions
        self._hasher = hasher
        self._clock = clock

    async def overview(self, principal: Principal) -> TeamOverview:
        organization_id = _organization_of(principal)
        now = self._clock.now()
        async with self._transactions.organization(organization_id) as store:
            invitations = [i for i in await store.invitations() if i.is_pending(now)]
            return TeamOverview(await store.members(), invitations)

    async def invite(self, principal: Principal, command: InviteCommand) -> IssuedInvitation:
        organization_id = _organization_of(principal)
        now = self._clock.now()
        invitation_id = validate_client_id(command.id, now)
        email = check_email(normalize_email(command.email))
        roles = parse_roles(command.roles)
        token = secrets.token_urlsafe(32)
        invitation = Invitation(
            invitation_id,
            organization_id,
            email,
            roles,
            principal.user_id,
            now,
            now + INVITATION_LIFETIME,
            None,
            None,
        )
        async with self._transactions.organization(organization_id) as store:
            await store.lock_organization(organization_id)
            await self._require_admin(store, principal)

            async def create() -> Invitation:
                if any(member.email == email for member in await store.members()):
                    raise AlreadyMemberError
                await store.insert_invitation(invitation, hash_token(token))
                await _audit(
                    store,
                    organization_id,
                    principal,
                    AuditAction.INVITATION_CREATED,
                    invitation_id,
                    roles,
                    now,
                )
                return invitation

            def same_content(existing: Invitation) -> bool:
                return (existing.email, existing.roles, existing.created_by) == (
                    email,
                    roles,
                    principal.user_id,
                )

            stored, created = await create_or_replay(
                find=lambda: store.find_invitation(invitation_id),
                create=create,
                same_content=same_content,
            )
        return IssuedInvitation(stored, token if created else None, created)

    async def revoke(self, principal: Principal, invitation_id: UUID) -> None:
        organization_id = _organization_of(principal)
        now = self._clock.now()
        async with self._transactions.organization(organization_id) as store:
            await store.lock_organization(organization_id)
            await self._require_admin(store, principal)
            invitation = await store.find_invitation(invitation_id)
            if invitation is None:
                raise NotFoundError
            if invitation.accepted_at is not None:
                raise InvitationAlreadyAcceptedError
            if invitation.revoked_at is None:
                await store.revoke_invitation(invitation_id, now)
                await _audit(
                    store,
                    organization_id,
                    principal,
                    AuditAction.INVITATION_REVOKED,
                    invitation_id,
                    None,
                    now,
                )

    async def set_roles(self, principal: Principal, user_id: UUID, roles: Iterable[str]) -> None:
        organization_id = _organization_of(principal)
        new_roles = parse_roles(roles)
        now = self._clock.now()
        async with self._transactions.organization(organization_id) as store:
            await store.lock_organization(organization_id)
            current = await self._require_admin(store, principal)
            if user_id not in current:
                raise NotFoundError
            ensure_an_admin_remains(current, user_id, new_roles)
            await store.replace_roles(organization_id, user_id, new_roles)
            await _audit(
                store,
                organization_id,
                principal,
                AuditAction.MEMBER_ROLES_CHANGED,
                user_id,
                new_roles,
                now,
            )

    async def remove(self, principal: Principal, user_id: UUID) -> None:
        organization_id = _organization_of(principal)
        now = self._clock.now()
        async with self._transactions.organization(organization_id) as store:
            await store.lock_organization(organization_id)
            current = await self._require_admin(store, principal)
            if user_id not in current:
                raise NotFoundError
            ensure_an_admin_remains(current, user_id, frozenset())
            await store.remove_member(organization_id, user_id, now)
            await store.revoke_sessions(organization_id, user_id, now)
            await _audit(
                store, organization_id, principal, AuditAction.MEMBER_REMOVED, user_id, None, now
            )

    async def accept_as_member(self, principal: Principal, token: str) -> UUID:
        now = self._clock.now()
        async with self._transactions.anonymous() as store:
            organization_id = await store.accept_invitation(
                hash_token(token), principal.user_id, now, uuid7()
            )
            if organization_id is None:
                raise InvitationNotValidError
        return organization_id

    async def accept_as_new_user(self, account: NewAccount) -> User:
        if len(account.password) < MIN_PASSWORD_LENGTH:
            raise PasswordTooShortError
        now = self._clock.now()
        email = normalize_email(account.email)
        async with self._transactions.anonymous() as store:
            if await store.find_user_by_email(email) is not None:
                raise InvitationNotValidError
            user = User(uuid7(), email, None, account.display_name)
            await store.insert_user(user, is_demo=False, now=now)
            organization_id = await store.accept_invitation(
                hash_token(account.token), user.id, now, uuid7()
            )
            if organization_id is None:
                raise InvitationNotValidError
            password_hash = self._hasher.hash(account.password)
            await store.update_password_hash(user.id, password_hash)
        return User(user.id, email, password_hash, account.display_name)

    async def _require_admin(
        self, store: TeamStore, principal: Principal
    ) -> dict[UUID, frozenset[Role]]:
        current = {member.user_id: member.roles for member in await store.members()}
        if Role.ADMIN not in current.get(principal.user_id, frozenset()):
            raise NotAdminError
        return current


async def _audit(
    store: TeamStore,
    organization_id: UUID,
    principal: Principal,
    action: AuditAction,
    entity_id: UUID,
    roles: frozenset[Role] | None,
    now: datetime,
) -> None:
    metadata = {} if roles is None else {"roles": sorted(role.value for role in roles)}
    await store.audit.record(
        AuditEvent(
            id=uuid7(),
            organization_id=organization_id,
            actor_user_id=principal.user_id,
            action=action,
            entity=action.value.split(".")[0],
            entity_id=entity_id,
            at=now,
            metadata=metadata,
        )
    )
