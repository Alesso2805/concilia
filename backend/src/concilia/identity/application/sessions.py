import hashlib
import hmac
import secrets
from base64 import urlsafe_b64encode
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid7

from concilia.audit.application.recorder import AuditAction, AuditEvent
from concilia.identity.application.ports import (
    IdentityStore,
    IdentityTransactions,
    PasswordHasher,
    RateLimiter,
)
from concilia.identity.domain.model import (
    OrganizationAccess,
    Session,
    normalize_email,
    session_expiry,
)
from concilia.shared.kernel.clock import Clock
from concilia.shared.kernel.principal import Principal


class InvalidCredentialsError(Exception):
    pass


class NotAMemberError(Exception):
    pass


class NotADemoError(Exception):
    pass


class TooManyAttemptsError(Exception):
    def __init__(self, retry_after: timedelta) -> None:
        super().__init__("too_many_attempts")
        self.retry_after = retry_after


@dataclass(frozen=True)
class LoginPolicy:
    window: timedelta
    max_per_email: int
    max_per_ip: int


@dataclass(frozen=True)
class IssuedSession:
    session_id: UUID
    token: str
    organization_id: UUID | None
    organizations: list[OrganizationAccess]


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_token(secret: bytes, session_id: UUID) -> str:
    digest = hmac.digest(secret, session_id.bytes, "sha256")
    return urlsafe_b64encode(digest).decode().rstrip("=")


def _window_start(now: datetime, window: timedelta) -> datetime:
    epoch = datetime(1970, 1, 1, tzinfo=now.tzinfo)
    return epoch + (now - epoch) // window * window


class SessionService:
    def __init__(
        self,
        transactions: IdentityTransactions,
        hasher: PasswordHasher,
        rate_limiter: RateLimiter,
        clock: Clock,
        *,
        policy: LoginPolicy,
        key_secret: bytes,
    ) -> None:
        self._transactions = transactions
        self._hasher = hasher
        self._rate_limiter = rate_limiter
        self._clock = clock
        self._policy = policy
        self._key_secret = key_secret
        self._dummy_hash = hasher.hash(secrets.token_urlsafe(16))

    def _key(self, kind: str, value: str) -> str:
        return hmac.new(self._key_secret, f"login:{kind}:{value}".encode(), "sha256").hexdigest()

    async def _check_rate(self, email: str, ip: str, now: datetime) -> None:
        window = self._policy.window
        by_email = await self._rate_limiter.hit(self._key("email", email), window, now)
        by_ip = await self._rate_limiter.hit(self._key("ip", ip), window, now)
        if by_email > self._policy.max_per_email or by_ip > self._policy.max_per_ip:
            raise TooManyAttemptsError(_window_start(now, window) + window - now)

    async def login(self, email: str, password: str, ip: str) -> IssuedSession:
        now = self._clock.now()
        email = normalize_email(email)
        await self._check_rate(email, ip, now)
        async with self._transactions.anonymous() as store:
            user = await store.find_user_by_email(email)
            if user is None or user.password_hash is None:
                self._hasher.verify(self._dummy_hash, password)
                raise InvalidCredentialsError
            if not self._hasher.verify(user.password_hash, password):
                raise InvalidCredentialsError
            if self._hasher.needs_rehash(user.password_hash):
                await store.update_password_hash(user.id, self._hasher.hash(password))
            organizations = await store.user_organizations(user.id)
            chosen = organizations[0].organization_id if len(organizations) == 1 else None
            return await self._issue(store, user.id, chosen, organizations, now)

    async def start(self, user_id: UUID) -> IssuedSession:
        now = self._clock.now()
        async with self._transactions.anonymous() as store:
            organizations = await store.user_organizations(user_id)
            chosen = organizations[0].organization_id if len(organizations) == 1 else None
            return await self._issue(store, user_id, chosen, organizations, now)

    async def _issue(
        self,
        store: IdentityStore,
        user_id: UUID,
        organization_id: UUID | None,
        organizations: list[OrganizationAccess],
        now: datetime,
    ) -> IssuedSession:
        token = secrets.token_urlsafe(32)
        session = Session(uuid7(), user_id, organization_id, now, now, session_expiry(now), None)
        await store.insert_session(session, hash_token(token))
        return IssuedSession(session.id, token, organization_id, organizations)

    async def resolve(self, token: str) -> Principal | None:
        now = self._clock.now()
        async with self._transactions.anonymous() as store:
            session = await store.find_session(hash_token(token))
            if session is None or not session.is_active(now):
                return None
            roles: frozenset[str] = frozenset()
            if session.organization_id is not None:
                organizations = await store.user_organizations(session.user_id)
                access = next(
                    (o for o in organizations if o.organization_id == session.organization_id),
                    None,
                )
                if access is None:
                    return None
                roles = frozenset(role.value for role in access.roles)
            if session.needs_touch(now):
                await store.touch_session(session.id, now)
            return Principal(session.user_id, session.id, session.organization_id, roles)

    async def organizations(self, user_id: UUID) -> list[OrganizationAccess]:
        async with self._transactions.anonymous() as store:
            return await store.user_organizations(user_id)

    async def choose_organization(
        self, principal: Principal, organization_id: UUID
    ) -> IssuedSession:
        now = self._clock.now()
        async with self._transactions.anonymous() as store:
            organizations = await store.user_organizations(principal.user_id)
            if organization_id not in {o.organization_id for o in organizations}:
                raise NotAMemberError
            await store.revoke_session(principal.session_id, now)
            return await self._issue(store, principal.user_id, organization_id, organizations, now)

    async def switch_demo_role(self, principal: Principal, role: str) -> IssuedSession:
        """Hand a demo visitor over to the demo user with another role, in a new session."""
        now = self._clock.now()
        organization_id = principal.organization_id
        if organization_id is None:
            raise NotADemoError
        async with self._transactions.organization(organization_id) as store:
            target = await store.demo_user_for_role(organization_id, principal.user_id, role, now)
            if target is None:
                raise NotADemoError
            await store.revoke_session(principal.session_id, now)
            organizations = await store.user_organizations(target)
            issued = await self._issue(store, target, organization_id, organizations, now)
            await store.audit.record(
                AuditEvent(
                    id=uuid7(),
                    organization_id=organization_id,
                    actor_user_id=principal.user_id,
                    action=AuditAction.DEMO_ROLE_SWITCHED,
                    entity="user",
                    entity_id=target,
                    at=now,
                    metadata={"roles": [role]},
                )
            )
            return issued

    async def logout(self, principal: Principal) -> None:
        async with self._transactions.anonymous() as store:
            await store.revoke_session(principal.session_id, self._clock.now())
