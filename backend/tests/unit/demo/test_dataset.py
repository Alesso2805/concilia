from collections import Counter, defaultdict
from uuid import UUID

import pytest

from concilia.demo.domain.dataset import (
    ENGINE_CASES,
    Case,
    Dataset,
    DemoMonth,
    build_dataset,
)
from concilia.matching.domain.engine import run_engine
from concilia.matching.domain.model import Credit, EngineInput, OpenReceivable, Proposal
from concilia.shared.kernel.normalization import (
    extract_doc_refs,
    normalize_doc_number,
    normalize_text,
)

REFERENCE_CASES = frozenset({Case.EXACT, Case.SEVERAL_DOCUMENTS, Case.ROUNDING, Case.DETRACTION})
SETTLED_IN_FULL = ENGINE_CASES - {Case.PAID_IN_PARTS}


@pytest.fixture(scope="module")
def dataset() -> Dataset:
    return build_dataset()


def _document(doc_number: str) -> str:
    normalized = normalize_doc_number(doc_number)
    assert normalized is not None
    return normalized


def _balances_before(dataset: Dataset, month: DemoMonth) -> dict[str, int]:
    balances: dict[str, int] = {}
    for earlier in dataset.months:
        if earlier.period >= month.period:
            break
        for receivable in earlier.receivables:
            balances[_document(receivable.doc_number)] = receivable.amount_cents
        for movement in earlier.movements:
            for document in movement.pays:
                if movement.case in SETTLED_IN_FULL:
                    balances[document] = 0
                elif movement.case in {Case.PAID_IN_PARTS, Case.PARTIAL, Case.AMBIGUOUS}:
                    balances[document] -= movement.amount_cents
    return {document: balance for document, balance in balances.items() if balance > 0}


def _engine_input(dataset: Dataset, month: DemoMonth) -> tuple[EngineInput, list[UUID]]:
    balances = _balances_before(dataset, month)
    receivables = []
    for index, receivable in enumerate(
        receivable
        for earlier in dataset.months
        if earlier.period <= month.period
        for receivable in earlier.receivables
    ):
        document = _document(receivable.doc_number)
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


def test_the_dataset_is_deterministic_and_sized_as_specified(dataset: Dataset) -> None:
    movements = sum(len(month.movements) for month in dataset.months)
    receivables = sum(len(month.receivables) for month in dataset.months)

    assert build_dataset() == dataset
    assert 480 <= movements <= 520
    assert 380 <= receivables <= 420


def test_documents_are_unique_and_amounts_only_repeat_on_purpose(dataset: Dataset) -> None:
    receivables = [r for month in dataset.months for r in month.receivables]
    documents = Counter(_document(r.doc_number) for r in receivables)
    amounts = Counter(r.amount_cents for r in receivables)
    ambiguous = sum(
        1 for month in dataset.months for m in month.movements if m.case == Case.AMBIGUOUS
    )

    assert max(documents.values()) == 1
    assert sum(count for count in amounts.values() if count > 1) == 2 * ambiguous


def test_the_engine_reaches_the_spec_targets_on_the_demo_dataset(dataset: Dataset) -> None:
    by_case: defaultdict[Case, list[bool]] = defaultdict(list)
    wrong: list[Proposal] = []
    for month in dataset.months:
        engine_input, credit_ids = _engine_input(dataset, month)
        documents = {r.id: r.doc_number_norm for r in engine_input.receivables}
        proposals = run_engine(engine_input)
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

    with_counterpart = sum(len(results) for results in by_case.values())
    by_references = sum(sum(by_case[case]) for case in REFERENCE_CASES)
    by_engine = sum(sum(by_case[case]) for case in ENGINE_CASES)
    assert wrong == []
    assert by_references / with_counterpart >= 0.70
    assert by_engine / with_counterpart >= 0.90
    assert all(all(by_case[case]) for case in ENGINE_CASES)
    assert not any(by_case[Case.AMBIGUOUS] + by_case[Case.PARTIAL])
