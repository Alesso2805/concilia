import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from concilia.audit.application.recorder import AuditRecorder
from concilia.banking.application.profile_config import ProfileConfig
from concilia.banking.domain.model import BankAccount, ImportProfile, ProfileKind
from concilia.shared.infrastructure.db import organization_transaction
from concilia.shared.kernel.ids import IdConflictError

ACCOUNT_COLUMNS = "id, bank, alias, number_last4, created_at, archived_at"
PROFILE_COLUMNS = "id, kind, bank_account_id, name, config, created_at, archived_at"


def _account(row: Any) -> BankAccount:
    return BankAccount(
        row.id, row.bank, row.alias, row.number_last4, row.created_at, row.archived_at
    )


def _profile(row: Any) -> ImportProfile:
    return ImportProfile(
        row.id,
        ProfileKind(row.kind),
        row.bank_account_id,
        row.name,
        dict(row.config),
        row.created_at,
        row.archived_at,
    )


class SqlBankingStore:
    def __init__(self, connection: AsyncConnection, audit: AuditRecorder) -> None:
        self._connection = connection
        self.audit = audit

    async def _execute(self, sql: str, **params: object) -> None:
        await self._connection.execute(text(sql), params)

    async def _insert(self, sql: str, **params: object) -> None:
        try:
            await self._execute(sql, **params)
        except IntegrityError as error:
            raise IdConflictError from error

    async def accounts(self) -> list[BankAccount]:
        rows = await self._connection.execute(
            text(f"SELECT {ACCOUNT_COLUMNS} FROM bank_accounts ORDER BY alias, id")  # noqa: S608
        )
        return [_account(row) for row in rows]

    async def find_account(self, account_id: UUID) -> BankAccount | None:
        row = (
            await self._connection.execute(
                text(f"SELECT {ACCOUNT_COLUMNS} FROM bank_accounts WHERE id = :id"),  # noqa: S608
                {"id": account_id},
            )
        ).first()
        return None if row is None else _account(row)

    async def insert_account(self, organization_id: UUID, account: BankAccount) -> None:
        await self._insert(
            """INSERT INTO bank_accounts (id, organization_id, bank, currency, alias, number_last4,
                                          created_at)
               VALUES (:id, :org, :bank, :currency, :alias, :last4, :now)""",
            id=account.id,
            org=organization_id,
            bank=account.bank,
            currency=account.currency,
            alias=account.alias,
            last4=account.number_last4,
            now=account.created_at,
        )

    async def update_account(self, account_id: UUID, bank: str, alias: str, last4: str) -> None:
        await self._execute(
            """UPDATE bank_accounts SET bank = :bank, alias = :alias, number_last4 = :last4
               WHERE id = :id""",
            bank=bank,
            alias=alias,
            last4=last4,
            id=account_id,
        )

    async def archive_account(self, account_id: UUID, now: datetime) -> None:
        await self._execute(
            "UPDATE bank_accounts SET archived_at = :now WHERE id = :id", now=now, id=account_id
        )

    async def profiles(self) -> list[ImportProfile]:
        rows = await self._connection.execute(
            text(f"SELECT {PROFILE_COLUMNS} FROM import_profiles ORDER BY kind, name, id")  # noqa: S608
        )
        return [_profile(row) for row in rows]

    async def find_profile(self, profile_id: UUID) -> ImportProfile | None:
        row = (
            await self._connection.execute(
                text(f"SELECT {PROFILE_COLUMNS} FROM import_profiles WHERE id = :id"),  # noqa: S608
                {"id": profile_id},
            )
        ).first()
        return None if row is None else _profile(row)

    async def insert_profile(self, organization_id: UUID, profile: ImportProfile) -> None:
        await self._insert(
            """INSERT INTO import_profiles (id, organization_id, kind, bank_account_id, name,
                                            config, created_at)
               VALUES (:id, :org, :kind, :account, :name, CAST(:config AS jsonb), :now)""",
            id=profile.id,
            org=organization_id,
            kind=profile.kind.value,
            account=profile.bank_account_id,
            name=profile.name,
            config=json.dumps(dict(profile.config)),
            now=profile.created_at,
        )

    async def update_profile(self, profile_id: UUID, name: str, config: ProfileConfig) -> None:
        await self._execute(
            """UPDATE import_profiles SET name = :name, config = CAST(:config AS jsonb)
               WHERE id = :id""",
            name=name,
            config=config.model_dump_json(),
            id=profile_id,
        )

    async def archive_profile(self, profile_id: UUID, now: datetime) -> None:
        await self._execute(
            "UPDATE import_profiles SET archived_at = :now WHERE id = :id", now=now, id=profile_id
        )


class SqlBankingTransactions:
    def __init__(
        self, engine: AsyncEngine, audit_factory: Callable[[AsyncConnection], AuditRecorder]
    ) -> None:
        self._engine = engine
        self._audit_factory = audit_factory

    @asynccontextmanager
    async def organization(self, organization_id: UUID) -> AsyncIterator[SqlBankingStore]:
        async with organization_transaction(self._engine, organization_id) as connection:
            yield SqlBankingStore(connection, self._audit_factory(connection))
