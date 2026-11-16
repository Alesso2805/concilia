import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid7

import httpx
import time_machine
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from concilia.shared.infrastructure.jobs import Runner
from concilia.worker import handlers
from tests.support.api import Member, create_member, xsrf_header
from tests.support.clock import FixedClock

NOW = datetime(2027, 2, 3, 15, 0, tzinfo=UTC)
CONFIG = {
    "version": 1,
    "format": "csv",
    "delimiter": ";",
    "encoding": "utf-8",
    "skip_rows": 0,
    "date_format": "DD/MM/YYYY",
    "decimal_separator": ",",
    "thousands_separator": ".",
    "columns": {"date": "Fecha", "description": "Detalle", "amount": "Importe"},
}
STATEMENT = (
    b"Fecha;Detalle;Importe\n"
    b"05/01/2027;PAGO FACT F001-123;1.180,00\n"
    b"06/01/2027;COMISION;-12,50\n"
    b"07/02/2027;TRANSF CLIENTE;500,00\n"
    b"08/02/2027;SIN MONTO;\n"
)


class AlwaysActive:
    def __init__(self, _connection: object) -> None:
        pass

    async def active(
        self, movement_ids: Sequence[UUID], receivable_ids: Sequence[UUID]
    ) -> set[UUID]:
        return {*movement_ids, *receivable_ids}

    async def pending(
        self, movement_ids: Sequence[UUID], receivable_ids: Sequence[UUID]
    ) -> set[UUID]:
        return {*movement_ids, *receivable_ids}


@dataclass(frozen=True)
class Setup:
    member: Member
    account_id: UUID
    profile_id: UUID

    @property
    def organization_id(self) -> UUID:
        return self.member.organization_ids[0]


def client_id() -> str:
    with time_machine.travel(NOW, tick=False):
        return str(uuid7())


async def statement_setup(owner_engine: AsyncEngine, roles: list[str] | None = None) -> Setup:
    member = await create_member(
        owner_engine, NOW, organizations={"Andina": roles or ["admin", "analyst"]}
    )
    account_id, profile_id = uuid7(), uuid7()
    async with owner_engine.begin() as connection:
        await connection.execute(
            text(
                """INSERT INTO bank_accounts (id, organization_id, bank, currency, alias,
                                              number_last4, created_at)
                   VALUES (:id, :org, 'BCP', 'PEN', 'Principal', '1234', :now)"""
            ),
            {"id": account_id, "org": member.organization_ids[0], "now": NOW},
        )
        await connection.execute(
            text(
                """INSERT INTO import_profiles (id, organization_id, kind, bank_account_id, name,
                                                config, created_at)
                   VALUES (:id, :org, 'bank_statement', :account, 'BCP CSV',
                           CAST(:config AS jsonb), :now)"""
            ),
            {
                "id": profile_id,
                "org": member.organization_ids[0],
                "account": account_id,
                "config": json.dumps(CONFIG),
                "now": NOW,
            },
        )
    return Setup(member, account_id, profile_id)


async def upload(
    client: httpx.AsyncClient,
    setup: Setup,
    content: bytes = STATEMENT,
    file_id: str | None = None,
    filename: str = "enero.csv",
) -> httpx.Response:
    return await client.post(
        "/api/app/imports",
        data={"id": file_id or client_id(), "import_profile_id": str(setup.profile_id)},
        files={"file": (filename, content, "text/csv")},
        headers=xsrf_header(client),
    )


async def work(worker_engine: AsyncEngine, clock: FixedClock) -> int:
    runner = Runner(worker_engine, clock, handlers(worker_engine, clock))
    done = 0
    while await runner.run_once():
        done += 1
    return done
