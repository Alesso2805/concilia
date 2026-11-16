from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid7

from concilia.banking.application.profile_config import StatementConfig
from concilia.banking.application.service import BankingStore
from concilia.banking.application.templates import TEMPLATES
from concilia.banking.domain.model import BankAccount, ImportProfile, ProfileKind


@dataclass(frozen=True)
class DemoAccount:
    bank: str
    alias: str
    number_last4: str
    statement_profile_name: str
    statement_config: StatementConfig
    receivables_profile_name: str


@dataclass(frozen=True)
class DemoBanking:
    account_id: UUID
    statement_profile_id: UUID
    receivables_profile_id: UUID


async def create_demo_banking(
    store: BankingStore, organization_id: UUID, spec: DemoAccount, now: datetime
) -> DemoBanking:
    """One bank account with a statement profile and a receivables profile from the template."""
    account = BankAccount(uuid7(), spec.bank, spec.alias, spec.number_last4, now, None)
    await store.insert_account(organization_id, account)
    receivables_template = next(t for t in TEMPLATES if t.kind == ProfileKind.RECEIVABLES)
    statement = ImportProfile(
        uuid7(),
        ProfileKind.BANK_STATEMENT,
        account.id,
        spec.statement_profile_name,
        spec.statement_config.model_dump(mode="json"),
        now,
        None,
    )
    receivables = ImportProfile(
        uuid7(),
        ProfileKind.RECEIVABLES,
        None,
        spec.receivables_profile_name,
        receivables_template.config.model_dump(mode="json"),
        now,
        None,
    )
    for profile in (statement, receivables):
        await store.insert_profile(organization_id, profile)
    return DemoBanking(account.id, statement.id, receivables.id)
