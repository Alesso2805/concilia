from datetime import date

import pytest

from concilia.matching.domain.model import (
    Application,
    DifferenceReason,
    MatchKey,
    Proposal,
    Rule,
)
from tests.support.engine import credit, receivable, run, summary


def test_exact_reference_and_amount() -> None:
    f123 = receivable("F001-123", 100_000)
    paid = credit(1, 100_000, "PAGO FACT F001-00000123")

    assert run([paid], [f123]) == [
        Proposal(
            rule=Rule.EXACT,
            score=100,
            credit_ids=(paid.id,),
            applications=(Application(f123.id, 100_000),),
            difference_cents=0,
            suggested_difference_reason=None,
            explanation="La descripción menciona F001-123 y el monto coincide con su saldo.",
        )
    ]


def test_exact_uses_the_only_mentioned_document_that_matches() -> None:
    receivables = [receivable("F001-1", 50_000), receivable("F001-2", 80_000)]

    proposals = run([credit(1, 80_000, "PAGO F001-1 F001-2")], receivables)

    assert summary(proposals, receivables) == [("R1", 100, [1], ["F001-2"])]


def test_exact_ignores_mentioned_documents_that_are_not_open_receivables() -> None:
    receivables = [receivable("F001-1", 50_000)]

    proposals = run([credit(1, 50_000, "PAGO F001-1 F009-9")], receivables)

    assert summary(proposals, receivables) == [("R1", 100, [1], ["F001-1"])]


def test_two_mentioned_documents_with_the_same_balance_are_ambiguous() -> None:
    receivables = [receivable("F001-1", 50_000), receivable("F001-2", 50_000)]

    assert run([credit(1, 50_000, "PAGO F001-1 F001-2")], receivables) == []


def test_the_oldest_credit_takes_a_shared_reference() -> None:
    receivables = [receivable("F001-1", 50_000)]
    later = credit(1, 50_000, "PAGO F001-1", booked_on=date(2027, 1, 10))
    earlier = credit(2, 50_000, "PAGO F001-1", booked_on=date(2027, 1, 5))

    proposals = run([later, earlier], receivables)

    assert summary(proposals, receivables) == [("R1", 100, [2], ["F001-1"])]


def test_several_documents_in_one_credit() -> None:
    receivables = [
        receivable("F001-1", 10_000),
        receivable("F001-2", 20_000),
        receivable("F001-3", 30_000),
    ]

    [proposal] = run([credit(1, 60_000, "PAGO F001-1 F001-2 Y F001-3")], receivables)

    assert summary([proposal], receivables) == [("R2", 95, [1], ["F001-1", "F001-2", "F001-3"])]
    assert [a.applied_cents for a in proposal.applications] == [10_000, 20_000, 30_000]
    assert proposal.difference_cents == 0
    assert proposal.explanation == (
        "La descripción menciona F001-1, F001-2 y F001-3 "
        "y la suma de sus saldos coincide con el abono."
    )


def test_several_documents_requires_every_mentioned_document() -> None:
    receivables = [receivable("F001-1", 10_000), receivable("F001-2", 20_000)]

    assert run([credit(1, 30_000, "PAGO F001-1 F001-2 F001-3")], receivables) == []


def test_rules_run_in_order_over_all_credits() -> None:
    receivables = [receivable("F001-1", 10_000), receivable("F001-2", 20_000)]
    older = credit(1, 30_000, "PAGO F001-1 F001-2", booked_on=date(2027, 1, 2))
    newer = credit(2, 10_000, "PAGO F001-1", booked_on=date(2027, 1, 3))

    proposals = run([older, newer], receivables)

    assert summary(proposals, receivables) == [("R1", 100, [2], ["F001-1"])]


@pytest.mark.parametrize(
    ("amount", "difference", "explanation"),
    [
        (99_950, -50, "la diferencia de S/ -0.50 está dentro de la tolerancia."),
        (100_500, 500, "la diferencia de S/ 5.00 está dentro de la tolerancia."),
    ],
)
def test_reference_within_tolerance(amount: int, difference: int, explanation: str) -> None:
    f1 = receivable("F001-1", 100_000)

    [proposal] = run([credit(1, amount, "PAGO F001-1")], [f1])

    assert proposal.rule == Rule.REFERENCE_WITH_DIFFERENCE
    assert proposal.score == 85
    assert proposal.applications == (Application(f1.id, 100_000),)
    assert proposal.difference_cents == difference
    assert proposal.suggested_difference_reason == DifferenceReason.ROUNDING
    assert proposal.explanation == f"La descripción menciona F001-1 y {explanation}"


@pytest.mark.parametrize("amount", [100_501, 99_499])
def test_reference_outside_tolerance_is_not_proposed(amount: int) -> None:
    assert run([credit(1, amount, "PAGO F001-1")], [receivable("F001-1", 100_000)]) == []


def test_reference_with_detraction() -> None:
    [proposal] = run([credit(1, 103_000, "PAGO F001-1")], [receivable("F001-1", 117_000)])

    assert proposal.rule == Rule.REFERENCE_WITH_DIFFERENCE
    assert proposal.difference_cents == -14_000
    assert proposal.suggested_difference_reason == DifferenceReason.DETRACTION
    assert proposal.explanation == (
        "La descripción menciona F001-1 y la diferencia de S/ -140.00 "
        "corresponde a una detracción del 12 %."
    )


def test_tolerance_comes_before_detraction() -> None:
    [proposal] = run([credit(1, 900, "PAGO F001-1")], [receivable("F001-1", 1_000)])

    assert proposal.suggested_difference_reason == DifferenceReason.ROUNDING


def test_two_mentioned_documents_within_tolerance_are_ambiguous() -> None:
    receivables = [receivable("F001-1", 100_000), receivable("F001-2", 100_200)]

    assert run([credit(1, 100_100, "PAGO F001-1 F001-2")], receivables) == []


def test_an_excluded_combination_is_not_proposed_again() -> None:
    f1 = receivable("F001-1", 50_000)
    paid = credit(1, 50_000, "PAGO F001-1")

    assert run([paid], [f1], excluded=[MatchKey(frozenset({paid.id}), frozenset({f1.id}))]) == []


def test_the_same_inputs_in_another_order_give_the_same_proposals() -> None:
    receivables = [receivable(f"F001-{n}", n * 1_000) for n in range(1, 6)]
    credits = [credit(n, n * 1_000, f"PAGO F001-{n}") for n in range(1, 6)]

    assert run(credits, receivables) == run(credits[::-1], receivables[::-1])
