from datetime import date, timedelta
from uuid import UUID

import pytest

from concilia.matching.domain.model import MatchKey
from tests.support.engine import credit, receivable, run, summary

ANDINA = "TRANSF COMERCIAL ANDINA"


def test_same_customer_several_receivables() -> None:
    receivables = [
        receivable("F001-1", 30_000, due_on=date(2027, 1, 18)),
        receivable("F001-2", 20_000, due_on=date(2027, 1, 19)),
        receivable("F001-3", 45_000, due_on=date(2027, 1, 20)),
    ]

    [proposal] = run([credit(1, 50_000, ANDINA)], receivables)

    assert summary([proposal], receivables) == [("R4", 80, [1], ["F001-1", "F001-2"])]
    assert proposal.difference_cents == 0
    assert proposal.explanation == (
        "El cliente de F001-1 y F001-2 coincide con la descripción (similitud 100) "
        "y esos cobros suman el abono."
    )


def test_same_customer_with_two_combinations_is_ambiguous() -> None:
    receivables = [receivable(f"F001-{n}", n * 10_000) for n in range(1, 5)]

    assert run([credit(1, 50_000, ANDINA)], receivables) == []


def test_same_customer_needs_a_single_most_similar_customer() -> None:
    receivables = [
        receivable("F001-1", 30_000),
        receivable("F001-2", 20_000),
        receivable("F002-1", 70_000, customer="COMERCIAL ANDINA SRL"),
    ]

    assert run([credit(1, 50_000, ANDINA)], receivables) == []


def test_same_customer_needs_a_strong_similarity() -> None:
    receivables = [receivable("F001-1", 30_000), receivable("F001-2", 20_000)]

    assert run([credit(1, 50_000, "TRANSF COMERCIAL ANDES")], receivables) == []


@pytest.mark.parametrize(
    ("due_on", "proposed"), [(date(2027, 3, 1), False), (date(2027, 1, 15), True)]
)
def test_same_customer_considers_the_ten_receivables_due_nearest(
    due_on: date, proposed: bool
) -> None:
    receivables = [
        receivable(f"F001-{n}", 100_000 + n, due_on=date(2027, 1, 10 + n)) for n in range(1, 11)
    ]
    receivables.append(receivable("F009-1", 7_000, due_on=due_on))

    proposals = run([credit(1, 107_001, ANDINA)], receivables)

    assert bool(proposals) == proposed


def test_paid_in_parts() -> None:
    f1 = receivable("F001-1", 90_000, issued_on=date(2027, 1, 1), due_on=date(2027, 1, 31))
    credits = [
        credit(2, 50_000, ANDINA, booked_on=date(2027, 1, 20)),
        credit(1, 40_000, ANDINA, booked_on=date(2027, 1, 10)),
    ]

    [proposal] = run(credits, [f1])

    assert summary([proposal], [f1]) == [("R5", 75, [1, 2], ["F001-1"])]
    assert proposal.applications[0].applied_cents == 90_000
    assert proposal.explanation == (
        "Los 2 abonos del cliente de F001-1, del 10/01/2027 al 20/01/2027, suman su saldo."
    )


def test_paid_in_parts_accepts_credits_a_whole_month_apart() -> None:
    f1 = receivable("F001-1", 90_000, issued_on=date(2027, 1, 1), due_on=date(2027, 1, 31))
    credits = [
        credit(1, 40_000, ANDINA, booked_on=date(2027, 1, 1)),
        credit(2, 50_000, ANDINA, booked_on=date(2027, 1, 31)),
    ]

    assert summary(run(credits, [f1]), [f1]) == [("R5", 75, [1, 2], ["F001-1"])]


@pytest.mark.parametrize(
    ("issued_on", "due_on"),
    [(date(2027, 1, 11), date(2027, 1, 31)), (date(2026, 11, 1), date(2026, 12, 20))],
)
def test_paid_in_parts_needs_every_credit_in_the_payment_window(
    issued_on: date, due_on: date
) -> None:
    f1 = receivable("F001-1", 90_000, issued_on=issued_on, due_on=due_on)
    credits = [
        credit(1, 40_000, ANDINA, booked_on=date(2027, 1, 10)),
        credit(2, 50_000, ANDINA, booked_on=date(2027, 1, 20)),
    ]

    assert run(credits, [f1]) == []


def test_paid_in_parts_with_two_combinations_is_ambiguous() -> None:
    f1 = receivable("F001-1", 90_000)
    credits = [
        credit(n, amount, ANDINA) for n, amount in enumerate([40_000, 50_000, 45_000, 45_000])
    ]

    assert run(credits, [f1]) == []


def test_paid_in_parts_visits_receivables_by_due_date() -> None:
    later_due = receivable("F001-1", 90_000, due_on=date(2027, 1, 25), id=UUID(int=100))
    earlier_due = receivable("F001-2", 90_000, due_on=date(2027, 1, 20), id=UUID(int=200))
    credits = [credit(1, 40_000, ANDINA), credit(2, 50_000, ANDINA)]

    proposals = run(credits, [later_due, earlier_due])

    assert summary(proposals, [later_due, earlier_due]) == [("R5", 75, [1, 2], ["F001-2"])]


def test_paid_in_parts_considers_the_twelve_credits_nearest_the_due_date() -> None:
    f1 = receivable("F001-1", 107_001, due_on=date(2027, 1, 15))
    near = [credit(n, 100_000 + n, ANDINA, booked_on=date(2027, 1, 8 + n)) for n in range(1, 13)]
    far = credit(13, 7_000, ANDINA, booked_on=date(2027, 1, 31))

    assert run([*near, far], [f1]) == []
    assert run([near[0], far], [f1]) != []


def test_amount_and_date() -> None:
    f1 = receivable("F001-1", 100_000)

    [proposal] = run([credit(1, 100_000, "DEPOSITO EN EFECTIVO")], [f1])

    assert summary([proposal], [f1]) == [("R6", 60, [1], ["F001-1"])]
    assert proposal.explanation == (
        "El monto coincide con el saldo de F001-1, la fecha está dentro del plazo "
        "y es el único candidato."
    )


def test_amount_and_date_with_a_similar_customer() -> None:
    [proposal] = run([credit(1, 100_000, ANDINA)], [receivable("F001-1", 100_000)])

    assert proposal.score == 75
    assert proposal.explanation.endswith(
        "; además, el cliente coincide con la descripción (similitud 100)."
    )


def test_amount_and_date_with_two_candidate_receivables_is_ambiguous() -> None:
    receivables = [receivable("F001-1", 100_000), receivable("F001-2", 100_000)]

    assert run([credit(1, 100_000, "DEPOSITO")], receivables) == []


def test_amount_and_date_with_two_credits_for_one_receivable_is_ambiguous() -> None:
    credits = [credit(1, 100_000, "DEPOSITO"), credit(2, 100_000, "DEPOSITO")]

    assert run(credits, [receivable("F001-1", 100_000)]) == []


def test_amount_and_date_counts_only_receivables_in_the_payment_window() -> None:
    receivables = [
        receivable("F001-1", 100_000),
        receivable("F001-2", 100_000, issued_on=date(2026, 9, 1), due_on=date(2026, 10, 1)),
    ]

    proposals = run([credit(1, 100_000, "DEPOSITO")], receivables)

    assert summary(proposals, receivables) == [("R6", 60, [1], ["F001-1"])]


@pytest.mark.parametrize(
    ("due_on", "booked_on", "proposed"),
    [
        (date(2028, 1, 31), date(2028, 3, 1), True),
        (date(2028, 1, 31), date(2028, 3, 2), False),
        (date(2027, 1, 31), date(2027, 3, 2), True),
        (date(2027, 1, 31), date(2027, 3, 3), False),
        (date(2028, 1, 30), date(2028, 2, 29), True),
        (date(2027, 12, 31), date(2028, 1, 30), True),
        (date(2027, 12, 31), date(2028, 1, 31), False),
    ],
)
def test_payment_window_across_month_and_year_ends(
    due_on: date, booked_on: date, proposed: bool
) -> None:
    f1 = receivable("F001-1", 100_000, issued_on=due_on - timedelta(days=30), due_on=due_on)

    proposals = run(
        [credit(1, 100_000, "DEPOSITO", booked_on=booked_on)],
        [f1],
        period=booked_on.replace(day=1),
    )

    assert bool(proposals) == proposed


def test_amount_and_date_proposes_higher_scores_first() -> None:
    receivables = [receivable("F001-1", 100_000), receivable("F001-2", 200_000)]
    credits = [
        credit(1, 100_000, "DEPOSITO", booked_on=date(2027, 1, 5)),
        credit(2, 200_000, ANDINA, booked_on=date(2027, 1, 20)),
    ]

    proposals = run(credits, receivables)

    assert summary(proposals, receivables) == [
        ("R6", 75, [2], ["F001-2"]),
        ("R6", 60, [1], ["F001-1"]),
    ]


def test_an_excluded_pair_is_not_proposed_by_a_later_rule() -> None:
    f1 = receivable("F001-1", 100_000)
    paid = credit(1, 100_000, "PAGO F001-1")
    excluded = MatchKey(frozenset({paid.id}), frozenset({f1.id}))

    assert run([paid], [f1], excluded=[excluded]) == []
