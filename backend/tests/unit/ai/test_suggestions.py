from datetime import date, timedelta
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from concilia.ai.domain.suggestions import (
    MAX_CANDIDATES,
    Candidate,
    CreditFacts,
    OpenReceivable,
    Proposal,
    choose_candidates,
    distribute,
    recompute,
    recompute_all,
)

CREDIT = CreditFacts(UUID(int=1), date(2027, 1, 10), 100_000, "PAGO GLORIA", "PAGO GLORIA")


def _receivable(
    n: int,
    available: int,
    *,
    due: date = date(2027, 1, 15),
    name: str = "OTRO CLIENTE SAC",
) -> OpenReceivable:
    return OpenReceivable(
        id=UUID(int=100 + n),
        doc_number=f"F001-{n}",
        doc_number_norm=f"F001-{n}",
        customer_name=name.title(),
        customer_name_norm=name,
        customer_tax_id=None,
        issued_on=date(2027, 1, 1),
        due_on=due,
        available_cents=available,
    )


def _candidates(*receivables: OpenReceivable) -> dict[str, Candidate]:
    return {f"C{n}": Candidate(f"C{n}", r) for n, r in enumerate(receivables, start=1)}


def _proposal(
    candidates: list[str],
    applied: list[tuple[str, int]] | None,
    reason: str | None = None,
) -> Proposal:
    return Proposal(candidates, applied, "high", "Coincide el monto.", reason)


def test_candidates_are_the_ten_closest_in_amount_then_customer_then_due_date() -> None:
    receivables = [_receivable(n, 100_000 + n * 1_000) for n in range(12)]
    receivables.append(_receivable(50, 0))
    receivables.append(_receivable(60, 101_000, name="GLORIA"))
    receivables.append(_receivable(61, 101_000, due=date(2027, 3, 1)))

    chosen = choose_candidates(CREDIT, receivables)

    assert len(chosen) == MAX_CANDIDATES
    assert [c.alias for c in chosen] == [f"C{n}" for n in range(1, 11)]
    assert [c.receivable.doc_number for c in chosen[:4]] == [
        "F001-0",
        "F001-60",
        "F001-1",
        "F001-61",
    ]
    assert all(c.receivable.available_cents > 0 for c in chosen)


def test_the_model_amounts_are_kept_when_every_one_is_valid() -> None:
    candidates = _candidates(_receivable(1, 60_000), _receivable(2, 50_000))

    suggestion = recompute(
        100_000, _proposal(["C1", "C2"], [("C1", 60_000), ("C2", 40_000)]), candidates
    )

    assert suggestion is not None
    assert [(a.alias, a.applied_cents) for a in suggestion.applied] == [
        ("C1", 60_000),
        ("C2", 40_000),
    ]
    assert (suggestion.difference_cents, suggestion.recomputed) == (0, False)


@pytest.mark.parametrize(
    "proposal",
    [
        _proposal(["C1", "C2"], None),
        _proposal(["C1", "C2"], [("C1", 70_000), ("C2", 30_000)]),
        _proposal(["C1", "C2", "C9"], [("C1", 60_000), ("C2", 40_000)]),
        _proposal(["C1", "C2"], [("C1", 60_000), ("C9", 40_000)]),
        _proposal(["C1", "C2"], [("C1", 60_000)]),
        _proposal(["C1", "C2"], [("C1", 60_000), ("C1", 1), ("C2", 40_000)]),
        _proposal(["C1", "C2"], [("C1", 0), ("C2", 40_000)]),
    ],
    ids=[
        "no amounts",
        "over balance",
        "invented candidate",
        "invented amount",
        "missing",
        "repeated",
        "zero",
    ],
)
def test_the_server_distributes_when_anything_was_dropped(proposal: Proposal) -> None:
    candidates = _candidates(
        _receivable(1, 60_000, due=date(2027, 1, 20)),
        _receivable(2, 50_000, due=date(2027, 1, 5)),
    )

    suggestion = recompute(100_000, proposal, candidates)

    assert suggestion is not None
    assert suggestion.recomputed
    assert [(a.alias, a.applied_cents) for a in suggestion.applied] == [
        ("C2", 50_000),
        ("C1", 50_000),
    ]
    assert suggestion.difference_cents == 0


def test_candidates_that_fit_in_the_credit_get_their_whole_balance() -> None:
    candidates = _candidates(_receivable(1, 30_000), _receivable(2, 40_000))

    applied = distribute(100_000, list(candidates.values()))

    assert [(a.alias, a.applied_cents) for a in applied] == [("C1", 30_000), ("C2", 40_000)]


def test_a_suggestion_without_any_sent_candidate_is_dropped() -> None:
    candidates = _candidates(_receivable(1, 30_000))

    assert recompute(100_000, _proposal(["C7"], None), candidates) is None
    assert recompute_all(
        100_000,
        [_proposal(["C7"], None), _proposal(["C1"], None)],
        list(candidates.values()),
    ) == [recompute(100_000, _proposal(["C1"], None), candidates)]


@pytest.mark.parametrize(
    ("credit", "reason", "expected"),
    [
        (100_000, "commission", None),
        (99_000, "commission", "commission"),
        (99_000, "overpayment", None),
        (101_000, "overpayment", "overpayment"),
        (99_000, "magic", None),
    ],
)
def test_a_difference_reason_must_fit_the_difference(
    credit: int, reason: str, expected: str | None
) -> None:
    candidates = _candidates(_receivable(1, 100_000))

    suggestion = recompute(credit, _proposal(["C1"], [("C1", 100_000)], reason), candidates)

    assert suggestion is not None
    assert suggestion.difference_cents == credit - 100_000
    assert suggestion.difference_reason == expected


def test_at_most_three_suggestions_are_kept() -> None:
    candidates = list(_candidates(_receivable(1, 100_000)).values())

    kept = recompute_all(100_000, [_proposal(["C1"], None)] * 5, candidates)

    assert len(kept) == 3


aliases = st.sampled_from([f"C{n}" for n in range(1, 13)])


@given(
    credit=st.integers(min_value=1, max_value=10**9),
    balances=st.lists(st.integers(min_value=1, max_value=10**9), min_size=1, max_size=10),
    sent=st.lists(aliases, min_size=1, max_size=10),
    amounts=st.one_of(
        st.none(),
        st.lists(st.tuples(aliases, st.integers(min_value=-10, max_value=10**9)), max_size=10),
    ),
)
def test_server_amounts_never_exceed_balances_nor_use_unsent_candidates(
    credit: int,
    balances: list[int],
    sent: list[str],
    amounts: list[tuple[str, int]] | None,
) -> None:
    candidates = _candidates(
        *(
            _receivable(n, balance, due=date(2027, 1, 1) + timedelta(days=n % 3))
            for n, balance in enumerate(balances)
        )
    )

    suggestion = recompute(credit, _proposal(sent, amounts), candidates)

    if not set(sent) & set(candidates):
        assert suggestion is None
        return
    assert suggestion is not None
    applied = {a.alias: a.applied_cents for a in suggestion.applied}
    assert set(applied) <= set(sent) & set(candidates)
    assert all(
        0 < cents <= candidates[alias].receivable.available_cents
        for alias, cents in applied.items()
    )
    assert suggestion.difference_cents == credit - sum(applied.values())
    if suggestion.recomputed:
        chosen = set(sent) & set(candidates)
        total = sum(candidates[alias].receivable.available_cents for alias in chosen)
        assert sum(applied.values()) == min(total, credit)
