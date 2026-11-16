from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid7

import httpx
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from concilia.ai.application.service import LlmChooser
from concilia.api import create_app
from concilia.identity.infrastructure.passwords import Argon2PasswordHasher
from concilia.shared.infrastructure.settings import ApiSettings
from tests.support.clock import FixedClock

ORIGIN = "https://test"
PASSWORD = "correct horse battery staple"


def settings_for_tests(database_url: str, **overrides: object) -> ApiSettings:
    values: dict[str, object] = {
        "database_url": database_url,
        "public_origin": ORIGIN,
        "csrf_secret": SecretStr("test-csrf-secret"),
        "rate_limit_secret": SecretStr("test-rate-limit-secret"),
        **overrides,
    }
    return ApiSettings.model_validate(values)


@asynccontextmanager
async def api_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as client:
        yield client
    await app.state.engine.dispose()


def build_app(
    database_url: str, clock: FixedClock, *, llm: LlmChooser | None = None, **overrides: object
) -> FastAPI:
    return create_app(settings_for_tests(database_url, **overrides), clock, llm)


@dataclass(frozen=True)
class Member:
    user_id: UUID
    email: str
    organization_ids: tuple[UUID, ...]


async def create_member(
    owner_engine: AsyncEngine,
    now: datetime,
    *,
    organizations: dict[str, list[str]],
    password: str | None = PASSWORD,
) -> Member:
    user_id = uuid7()
    email = f"{user_id}@example.test"
    password_hash = Argon2PasswordHasher().hash(password) if password else None
    organization_ids = []
    async with owner_engine.begin() as connection:
        await connection.execute(
            text(
                """INSERT INTO users (id, email, password_hash, display_name, is_demo, created_at)
                   VALUES (:id, :email, :hash, 'Test user', :is_demo, :now)"""
            ),
            {
                "id": user_id,
                "email": email,
                "hash": password_hash,
                "is_demo": password is None,
                "now": now,
            },
        )
        for name, roles in organizations.items():
            organization_id = uuid7()
            organization_ids.append(organization_id)
            await connection.execute(
                text("INSERT INTO organizations (id, name, created_at) VALUES (:id, :name, :now)"),
                {"id": organization_id, "name": name, "now": now},
            )
            await connection.execute(
                text(
                    """INSERT INTO memberships (organization_id, user_id, created_at)
                       VALUES (:org, :user, :now)"""
                ),
                {"org": organization_id, "user": user_id, "now": now},
            )
            for role in roles:
                await connection.execute(
                    text(
                        """INSERT INTO member_roles (organization_id, user_id, role)
                           VALUES (:org, :user, :role)"""
                    ),
                    {"org": organization_id, "user": user_id, "role": role},
                )
    return Member(user_id, email, tuple(organization_ids))


def xsrf_header(client: httpx.AsyncClient) -> dict[str, str]:
    return {"X-XSRF-TOKEN": client.cookies.get("__Host-XSRF-TOKEN") or ""}


async def add_member(
    owner_engine: AsyncEngine, now: datetime, organization_id: UUID, roles: list[str]
) -> Member:
    user_id = uuid7()
    email = f"{user_id}@example.test"
    async with owner_engine.begin() as connection:
        await connection.execute(
            text(
                """INSERT INTO users (id, email, password_hash, display_name, created_at)
                   VALUES (:id, :email, :hash, 'Test member', :now)"""
            ),
            {
                "id": user_id,
                "email": email,
                "hash": Argon2PasswordHasher().hash(PASSWORD),
                "now": now,
            },
        )
        await connection.execute(
            text(
                """INSERT INTO memberships (organization_id, user_id, created_at)
                   VALUES (:org, :user, :now)"""
            ),
            {"org": organization_id, "user": user_id, "now": now},
        )
        for role in roles:
            await connection.execute(
                text(
                    """INSERT INTO member_roles (organization_id, user_id, role)
                       VALUES (:org, :user, :role)"""
                ),
                {"org": organization_id, "user": user_id, "role": role},
            )
    return Member(user_id, email, (organization_id,))


@asynccontextmanager
async def signed_in(app: FastAPI, email: str | None = None) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as client:
        if email is not None:
            response = await client.post(
                "/api/public/login", json={"email": email, "password": PASSWORD}
            )
            response.raise_for_status()
        yield client
