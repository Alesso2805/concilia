from collections import Counter

import pytest

from concilia.demo.domain.dataset import (
    ENGINE_CASES,
    Case,
    Dataset,
    build_dataset,
)
from tests.support.demo_engine import REFERENCE_CASES, document_of, engine_results


@pytest.fixture(scope="module")
def dataset() -> Dataset:
    return build_dataset()


def test_the_dataset_is_deterministic_and_sized_as_specified(dataset: Dataset) -> None:
    movements = sum(len(month.movements) for month in dataset.months)
    receivables = sum(len(month.receivables) for month in dataset.months)

    assert build_dataset() == dataset
    assert 480 <= movements <= 520
    assert 380 <= receivables <= 420


def test_documents_are_unique_and_amounts_only_repeat_on_purpose(dataset: Dataset) -> None:
    receivables = [r for month in dataset.months for r in month.receivables]
    documents = Counter(document_of(r.doc_number) for r in receivables)
    amounts = Counter(r.amount_cents for r in receivables)
    ambiguous = sum(
        1 for month in dataset.months for m in month.movements if m.case == Case.AMBIGUOUS
    )

    assert max(documents.values()) == 1
    assert sum(count for count in amounts.values() if count > 1) == 2 * ambiguous


def test_the_engine_reaches_the_spec_targets_on_the_demo_dataset(dataset: Dataset) -> None:
    results = engine_results(dataset)

    assert results.wrong == []
    assert results.matched(REFERENCE_CASES) / results.with_counterpart >= 0.70
    assert results.matched(ENGINE_CASES) / results.with_counterpart >= 0.90
    assert all(all(results.by_case[case]) for case in ENGINE_CASES)
    assert not any(results.by_case[Case.AMBIGUOUS] + results.by_case[Case.PARTIAL])
