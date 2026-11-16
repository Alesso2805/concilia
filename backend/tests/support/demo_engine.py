from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from concilia.demo.domain.dataset import ENGINE_CASES, Case, Dataset, DemoMonth
from concilia.matching.domain.engine import run_engine
from concilia.matching.domain.model import Credit, EngineInput, OpenReceivable, Proposal
from concilia.shared.kernel.normalization import (
    extract_doc_refs,
    normalize_doc_number,
    normalize_text,
)

REFERENCE_CASES = frozenset({Case.EXACT, Case.SEVERAL_DOCUMENTS, Case.ROUNDING, Case.DETRACTION})
SETTLED_IN_FULL = ENGINE_CASES - {Case.PAID_IN_PARTS}


def document_of(doc_number: str) -> str:
    normalized = normalize_doc_number(doc_number)
    assert normalized is not None
    return normalized


def balances_before(dataset: Dataset, month: DemoMonth) -> dict[str, int]:
    balances: dict[str, int] = {}
    for earlier in dataset.months:
        if earlier.period >= month.period:
            break
        for receivable in earlier.receivables:
            balances[document_of(receivable.doc_number)] = receivable.amount_cents
        for movement in earlier.movements:
            for document in movement.pays:
                if movement.case in SETTLED_IN_FULL:
                    balances[document] = 0
                elif movement.case in {Case.PAID_IN_PARTS, Case.PARTIAL, Case.AMBIGUOUS}:
                    balances[document] -= movement.amount_cents
    return {document: balance for document, balance in balances.items() if balance > 0}


def engine_input(dataset: Dataset, month: DemoMonth) -> tuple[EngineInput, list[UUID]]:
    balances = balances_before(dataset, month)
    receivables = []
    for index, receivable in enumerate(
        receivable
        for earlier in dataset.months
        if earlier.period <= month.period
        for receivable in earlier.receivables
    ):
        document = document_of(receivable.doc_number)
        available = (
            receivable.amount_cents if receivable in month.receivables else balances.get(document)
        )
        if available:
            receivables.append(
                OpenReceivable(
                    UUID(int=1_000_000 + index),
                    document,
                    normalize_text(receivable.customer_name),
                    receivable.customer_tax_id,
                    receivable.issued_on,
                    receivable.due_on,
                    available,
                )
            )
    credit_ids = [UUID(int=index) for index in range(len(month.movements))]
    credits = tuple(
        Credit(
            credit_ids[index],
            movement.booked_on,
            movement.amount_cents,
            normalize_text(movement.description),
            tuple(extract_doc_refs(movement.description)),
        )
        for index, movement in enumerate(month.movements)
        if movement.amount_cents > 0
    )
    return EngineInput(month.period, credits, tuple(receivables)), credit_ids


@dataclass(frozen=True)
class EngineResults:
    """How the engine did on every credit that pays a receivable, by dataset case."""

    by_case: dict[Case, list[bool]]
    wrong: list[Proposal]

    @property
    def with_counterpart(self) -> int:
        return sum(len(results) for results in self.by_case.values())

    def matched(self, cases: frozenset[Case]) -> int:
        return sum(sum(self.by_case.get(case, [])) for case in cases)


def engine_results(dataset: Dataset) -> EngineResults:
    by_case: defaultdict[Case, list[bool]] = defaultdict(list)
    wrong: list[Proposal] = []
    for month in dataset.months:
        month_input, credit_ids = engine_input(dataset, month)
        documents = {r.id: r.doc_number_norm for r in month_input.receivables}
        proposals = run_engine(month_input)
        found = {
            credit: frozenset(documents[a.receivable_id] for a in proposal.applications)
            for proposal in proposals
            for credit in proposal.credit_ids
        }
        for index, movement in enumerate(month.movements):
            if not movement.pays:
                continue
            proposed = found.get(credit_ids[index])
            by_case[movement.case].append(proposed == frozenset(movement.pays))
            if proposed is not None and proposed != frozenset(movement.pays):
                wrong.extend(p for p in proposals if credit_ids[index] in p.credit_ids)
    return EngineResults(dict(by_case), wrong)
