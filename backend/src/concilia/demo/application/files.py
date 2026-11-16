from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from concilia.demo.domain.dataset import build_dataset
from concilia.demo.domain.files import download_receivables, download_statement
from concilia.shared.kernel.principal import Principal

type DemoFileKind = Literal["statement", "receivables"]


class NoDemoFilesError(Exception):
    pass


class DemoQueries(Protocol):
    async def is_demo(self, organization_id: UUID) -> bool: ...


class DemoReadTransactions(Protocol):
    def organization(self, organization_id: UUID) -> AbstractAsyncContextManager[DemoQueries]: ...


@dataclass(frozen=True)
class DemoFile:
    filename: str
    content: bytes


class DemoFilesService:
    """The month a demo visitor imports by hand, as the files a bank and an ERP would export."""

    def __init__(self, transactions: DemoReadTransactions) -> None:
        self._transactions = transactions

    async def file(self, principal: Principal, kind: DemoFileKind) -> DemoFile:
        organization_id = principal.organization_id
        if organization_id is None:
            raise NoDemoFilesError
        async with self._transactions.organization(organization_id) as queries:
            if not await queries.is_demo(organization_id):
                raise NoDemoFilesError
        dataset = build_dataset()
        month = dataset.months[-1].period.strftime("%Y-%m")
        if kind == "statement":
            return DemoFile(f"extracto-{month}.csv", download_statement(dataset))
        return DemoFile(f"cobros-{month}.csv", download_receivables(dataset))
