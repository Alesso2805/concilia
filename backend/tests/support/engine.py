from collections.abc import Iterable
from datetime import date
from uuid import NAMESPACE_OID, UUID, uuid5

from concilia.matching.domain.engine import run_engine
from concilia.matching.domain.model import (
    Credit,
    EngineInput,
    EnginePolicy,
    MatchKey,
    OpenReceivable,
    Proposal,
)
from concilia.shared.kernel.normalization import extract_doc_refs, normalize_text

PERIOD = date(2027, 1, 1)
CUSTOMER = "COMERCIAL ANDINA SAC"


def credit(
    number: int, amount_cents: int, description: str, booked_on: date = date(2027, 1, 15)
) -> Credit:
    return Credit(
        id=UUID(int=number),
        booked_on=booked_on,
        amount_cents=amount_cents,
        description_norm=normalize_text(description),
        doc_refs=tuple(extract_doc_refs(description)),
    )


def receivable(
    document: str,
    available_cents: int,
    *,
    customer: str = CUSTOMER,
    tax_id: str | None = None,
    issued_on: date = date(2026, 12, 20),
    due_on: date = date(2027, 1, 20),
    id: UUID | None = None,
) -> OpenReceivable:
    return OpenReceivable(
        id=id or uuid5(NAMESPACE_OID, document),
        doc_number_norm=document,
        customer_name_norm=normalize_text(customer),
        customer_tax_id=tax_id,
        issued_on=issued_on,
        due_on=due_on,
        available_cents=available_cents,
    )


def run(
    credits: Iterable[Credit],
    receivables: Iterable[OpenReceivable],
    *,
    period: date = PERIOD,
    policy: EnginePolicy | None = None,
    excluded: Iterable[MatchKey] = (),
) -> list[Proposal]:
    return run_engine(
        EngineInput(
            period=period,
            credits=tuple(credits),
            receivables=tuple(receivables),
            policy=policy or EnginePolicy(),
            excluded=frozenset(excluded),
        )
    )


type Summary = tuple[str, int, list[int], list[str]]


def summary(proposals: Iterable[Proposal], receivables: Iterable[OpenReceivable]) -> list[Summary]:
    documents = {r.id: r.doc_number_norm for r in receivables}
    return [
        (
            proposal.rule.value,
            proposal.score,
            [credit_id.int for credit_id in proposal.credit_ids],
            [documents[application.receivable_id] for application in proposal.applications],
        )
        for proposal in proposals
    ]
