from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid7

from concilia.audit.application.recorder import AuditAction, AuditEvent, AuditRecorder
from concilia.banking.application.profile_config import CONFIG_MODELS, ProfileConfig
from concilia.banking.application.templates import TEMPLATES, Template
from concilia.banking.domain.model import BankAccount, ImportProfile, ProfileKind, check_last4
from concilia.shared.kernel.clock import Clock
from concilia.shared.kernel.ids import create_or_replay, validate_client_id
from concilia.shared.kernel.principal import Principal

ADMIN = "admin"


class NotAdminError(Exception):
    pass


class NotFoundError(Exception):
    pass


class ArchivedError(Exception):
    pass


class KindMismatchError(ValueError):
    pass


class BankingStore(Protocol):
    audit: AuditRecorder

    async def accounts(self) -> list[BankAccount]: ...

    async def find_account(self, account_id: UUID) -> BankAccount | None: ...

    async def insert_account(self, organization_id: UUID, account: BankAccount) -> None: ...

    async def update_account(self, account_id: UUID, bank: str, alias: str, last4: str) -> None: ...

    async def archive_account(self, account_id: UUID, now: datetime) -> None: ...

    async def profiles(self) -> list[ImportProfile]: ...

    async def find_profile(self, profile_id: UUID) -> ImportProfile | None: ...

    async def insert_profile(self, organization_id: UUID, profile: ImportProfile) -> None: ...

    async def update_profile(self, profile_id: UUID, name: str, config: ProfileConfig) -> None: ...

    async def archive_profile(self, profile_id: UUID, now: datetime) -> None: ...


class BankingTransactions(Protocol):
    def organization(self, organization_id: UUID) -> AbstractAsyncContextManager[BankingStore]: ...


@dataclass(frozen=True)
class AccountCommand:
    bank: str
    alias: str
    number_last4: str


@dataclass(frozen=True)
class ProfileCommand:
    kind: ProfileKind
    name: str
    config: ProfileConfig
    bank_account_id: UUID | None = None


def _organization(principal: Principal, *, admin: bool) -> UUID:
    if principal.organization_id is None or (admin and ADMIN not in principal.roles):
        raise NotAdminError
    return principal.organization_id


def _check_kind(kind: ProfileKind, config: ProfileConfig) -> None:
    if not isinstance(config, CONFIG_MODELS[kind]):
        raise KindMismatchError


class BankingService:
    def __init__(self, transactions: BankingTransactions, clock: Clock) -> None:
        self._transactions = transactions
        self._clock = clock

    def templates(self) -> tuple[Template, ...]:
        return TEMPLATES

    async def accounts(self, principal: Principal) -> list[BankAccount]:
        organization_id = _organization(principal, admin=False)
        async with self._transactions.organization(organization_id) as store:
            return await store.accounts()

    async def create_account(
        self, principal: Principal, account_id: UUID, command: AccountCommand
    ) -> tuple[BankAccount, bool]:
        organization_id = _organization(principal, admin=True)
        now = self._clock.now()
        validate_client_id(account_id, now)
        account = BankAccount(
            account_id,
            command.bank.strip(),
            command.alias.strip(),
            check_last4(command.number_last4),
            now,
            None,
        )
        async with self._transactions.organization(organization_id) as store:

            async def create() -> BankAccount:
                await store.insert_account(organization_id, account)
                await _audit(
                    store,
                    organization_id,
                    principal,
                    AuditAction.BANK_ACCOUNT_CREATED,
                    account_id,
                    now,
                )
                return account

            def same_content(existing: BankAccount) -> bool:
                return (existing.bank, existing.alias, existing.number_last4) == (
                    account.bank,
                    account.alias,
                    account.number_last4,
                )

            return await create_or_replay(
                find=lambda: store.find_account(account_id),
                create=create,
                same_content=same_content,
            )

    async def update_account(
        self, principal: Principal, account_id: UUID, command: AccountCommand
    ) -> None:
        organization_id = _organization(principal, admin=True)
        last4 = check_last4(command.number_last4)
        async with self._transactions.organization(organization_id) as store:
            await _active_account(store, account_id)
            await store.update_account(
                account_id, command.bank.strip(), command.alias.strip(), last4
            )
            await _audit(
                store,
                organization_id,
                principal,
                AuditAction.BANK_ACCOUNT_UPDATED,
                account_id,
                self._clock.now(),
            )

    async def archive_account(self, principal: Principal, account_id: UUID) -> None:
        organization_id = _organization(principal, admin=True)
        now = self._clock.now()
        async with self._transactions.organization(organization_id) as store:
            account = await store.find_account(account_id)
            if account is None:
                raise NotFoundError
            if account.archived_at is None:
                await store.archive_account(account_id, now)
                await _audit(
                    store,
                    organization_id,
                    principal,
                    AuditAction.BANK_ACCOUNT_ARCHIVED,
                    account_id,
                    now,
                )

    async def profiles(self, principal: Principal) -> list[ImportProfile]:
        organization_id = _organization(principal, admin=False)
        async with self._transactions.organization(organization_id) as store:
            return await store.profiles()

    async def create_profile(
        self, principal: Principal, profile_id: UUID, command: ProfileCommand
    ) -> tuple[ImportProfile, bool]:
        organization_id = _organization(principal, admin=True)
        now = self._clock.now()
        validate_client_id(profile_id, now)
        _check_kind(command.kind, command.config)
        if (command.kind == ProfileKind.BANK_STATEMENT) != (command.bank_account_id is not None):
            raise KindMismatchError
        profile = ImportProfile(
            profile_id,
            command.kind,
            command.bank_account_id,
            command.name.strip(),
            command.config.model_dump(mode="json"),
            now,
            None,
        )
        async with self._transactions.organization(organization_id) as store:

            async def create() -> ImportProfile:
                if command.bank_account_id is not None:
                    await _active_account(store, command.bank_account_id)
                await store.insert_profile(organization_id, profile)
                await _audit(
                    store,
                    organization_id,
                    principal,
                    AuditAction.IMPORT_PROFILE_CREATED,
                    profile_id,
                    now,
                    {"kind": command.kind.value},
                )
                return profile

            def same_content(existing: ImportProfile) -> bool:
                return (
                    existing.kind,
                    existing.bank_account_id,
                    existing.name,
                    dict(existing.config),
                ) == (profile.kind, profile.bank_account_id, profile.name, dict(profile.config))

            return await create_or_replay(
                find=lambda: store.find_profile(profile_id),
                create=create,
                same_content=same_content,
            )

    async def update_profile(
        self, principal: Principal, profile_id: UUID, name: str, config: ProfileConfig
    ) -> None:
        organization_id = _organization(principal, admin=True)
        async with self._transactions.organization(organization_id) as store:
            profile = await store.find_profile(profile_id)
            if profile is None:
                raise NotFoundError
            if profile.archived_at is not None:
                raise ArchivedError
            _check_kind(profile.kind, config)
            await store.update_profile(profile_id, name.strip(), config)
            await _audit(
                store,
                organization_id,
                principal,
                AuditAction.IMPORT_PROFILE_UPDATED,
                profile_id,
                self._clock.now(),
            )

    async def archive_profile(self, principal: Principal, profile_id: UUID) -> None:
        organization_id = _organization(principal, admin=True)
        now = self._clock.now()
        async with self._transactions.organization(organization_id) as store:
            profile = await store.find_profile(profile_id)
            if profile is None:
                raise NotFoundError
            if profile.archived_at is None:
                await store.archive_profile(profile_id, now)
                await _audit(
                    store,
                    organization_id,
                    principal,
                    AuditAction.IMPORT_PROFILE_ARCHIVED,
                    profile_id,
                    now,
                )


async def _active_account(store: BankingStore, account_id: UUID) -> BankAccount:
    account = await store.find_account(account_id)
    if account is None:
        raise NotFoundError
    if account.archived_at is not None:
        raise ArchivedError
    return account


async def _audit(
    store: BankingStore,
    organization_id: UUID,
    principal: Principal,
    action: AuditAction,
    entity_id: UUID,
    now: datetime,
    metadata: dict[str, str] | None = None,
) -> None:
    await store.audit.record(
        AuditEvent(
            id=uuid7(),
            organization_id=organization_id,
            actor_user_id=principal.user_id,
            action=action,
            entity=action.value.split(".")[0],
            entity_id=entity_id,
            at=now,
            metadata=metadata or {},
        )
    )
