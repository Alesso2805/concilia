import calendar
import math
import random
from collections import Counter
from datetime import date, timedelta
from fractions import Fraction
from uuid import UUID

from hypothesis import given, settings
from hypothesis import strategies as st

from concilia.matching.domain.engine import run_engine
from concilia.matching.domain.model import (
    Credit,
    DifferenceReason,
    EngineInput,
    MatchKey,
    OpenReceivable,
    Proposal,
    Rule,
)
from concilia.matching.domain.similarity import customer_key
from concilia.shared.kernel.normalization import (
    customer_similarity,
    extract_doc_refs,
    normalize_text,
)

CUSTOMERS = [
    ("COMERCIAL ANDINA SAC", None),
    ("COMERCIAL ANDINA SRL", None),
    ("GLORIA SA", "20100190797"),
    ("DISTRIBUIDORA NORTE EIRL", "20512345678"),
]
AMOUNTS = [10_000, 20_000, 30_000, 50_000, 117_000]
DELTAS = [-14_040, -500, -100, -50, 0, 50, 100, 501]
NOISE = ["PAGO", "TRANSF", "DEPOSITO", "ABONO", "CLIENTE"]


@st.composite
def engine_inputs(draw: st.DrawFn) -> EngineInput:
    period = date(draw(st.sampled_from([2027, 2028])), draw(st.sampled_from([1, 2, 12])), 1)
    days = calendar.monthrange(period.year, period.month)[1]
    receivables = []
    for n in range(draw(st.integers(0, 8))):
        name, tax_id = draw(st.sampled_from(CUSTOMERS))
        issued_on = period + timedelta(days=draw(st.integers(-60, days - 1)))
        receivables.append(
            OpenReceivable(
                id=UUID(int=1_000 + n),
                doc_number_norm=f"F001-{n}",
                customer_name_norm=normalize_text(name),
                customer_tax_id=tax_id,
                issued_on=issued_on,
                due_on=issued_on + timedelta(days=draw(st.integers(0, 45))),
                available_cents=draw(st.sampled_from(AMOUNTS)),
            )
        )
    credits = []
    for n in range(draw(st.integers(0, 8))):
        paid = draw(st.lists(st.sampled_from(receivables), max_size=3)) if receivables else []
        amount = sum(r.available_cents for r in set(paid)) or draw(st.sampled_from(AMOUNTS))
        amount = draw(
            st.sampled_from([amount, amount // 2, amount + draw(st.sampled_from(DELTAS))])
        )
        words = draw(st.lists(st.sampled_from(NOISE), max_size=2))
        words += [r.doc_number_norm for r in dict.fromkeys(paid) if draw(st.booleans())]
        words += [f"F001-{i}" for i in draw(st.lists(st.integers(0, 9), max_size=1))]
        payers = [(r.customer_name_norm, r.customer_tax_id) for r in paid]
        name, tax_id = draw(st.sampled_from(payers or CUSTOMERS))
        words += draw(st.sampled_from([[], [name], [tax_id or ""], name.split()[:1]]))
        description = " ".join(draw(st.permutations(words)))
        credits.append(
            Credit(
                id=UUID(int=n + 1),
                booked_on=period + timedelta(days=draw(st.integers(0, days - 1))),
                amount_cents=amount if amount > 0 else AMOUNTS[0],
                description_norm=normalize_text(description),
                doc_refs=tuple(extract_doc_refs(description)),
            )
        )
    excluded = {
        MatchKey(frozenset({credits[c].id}), frozenset({receivables[r].id}))
        for c, r in draw(st.lists(st.tuples(st.integers(0, 7), st.integers(0, 7)), max_size=3))
        if c < len(credits) and r < len(receivables)
    }
    return EngineInput(
        period=period,
        credits=tuple(credits),
        receivables=tuple(receivables),
        excluded=frozenset(excluded),
    )


def _strong_similarity(world: EngineInput, credit: Credit, customer: str) -> bool:
    return any(
        customer_similarity(
            customer_name_norm=r.customer_name_norm,
            customer_tax_id=r.customer_tax_id,
            description_norm=credit.description_norm,
        )
        >= 85
        for r in world.receivables
        if customer_key(r) == customer
    )


def _in_window(credit: Credit, receivable: OpenReceivable) -> bool:
    return receivable.issued_on <= credit.booked_on <= receivable.due_on + timedelta(days=30)


def _detraction_matches(amount: int, balance: int, rates: tuple[int, ...]) -> bool:
    for rate in rates:
        soles = math.floor(Fraction(balance * rate, 1_000_000) + Fraction(1, 2))
        if abs(amount - (balance - soles * 100)) <= 100:
            return True
    return False


def _assert_rule_holds(world: EngineInput, proposal: Proposal) -> None:
    credits = [c for c in world.credits if c.id in proposal.credit_ids]
    by_id = {r.id: r for r in world.receivables}
    receivables = [by_id[a.receivable_id] for a in proposal.applications]
    total = sum(c.amount_cents for c in credits)
    balance = sum(r.available_cents for r in receivables)
    policy = world.policy
    match proposal.rule:
        case Rule.EXACT:
            [credit], [receivable] = credits, receivables
            assert receivable.doc_number_norm in credit.doc_refs
            assert (proposal.score, total) == (100, balance)
        case Rule.SEVERAL_DOCUMENTS:
            [credit] = credits
            assert sorted(r.doc_number_norm for r in receivables) == sorted(credit.doc_refs)
            assert (proposal.score, len(receivables), total) == (95, len(credit.doc_refs), balance)
            assert len(receivables) >= 2
        case Rule.REFERENCE_WITH_DIFFERENCE:
            [credit], [receivable] = credits, receivables
            assert receivable.doc_number_norm in credit.doc_refs
            assert proposal.score == 85
            difference = total - balance
            tolerance = max(policy.tolerance_min_cents, balance * policy.tolerance_bp // 10_000)
            if proposal.suggested_difference_reason == DifferenceReason.DETRACTION:
                assert abs(difference) > tolerance
                assert _detraction_matches(total, balance, policy.detraction_rates_bp)
            else:
                assert abs(difference) <= tolerance
        case Rule.SAME_CUSTOMER:
            [credit] = credits
            [customer] = {customer_key(r) for r in receivables}
            assert 2 <= len(receivables) <= 4
            assert (proposal.score, total) == (80, balance)
            assert _strong_similarity(world, credit, customer)
        case Rule.PAID_IN_PARTS:
            [receivable] = receivables
            dates = [c.booked_on for c in credits]
            assert 2 <= len(credits) <= 3
            assert (proposal.score, total) == (75, balance)
            assert max(dates) - min(dates) <= timedelta(days=30)
            for credit in credits:
                assert _in_window(credit, receivable)
                assert _strong_similarity(world, credit, customer_key(receivable))
        case Rule.AMOUNT_AND_DATE:
            [credit], [receivable] = credits, receivables
            assert total == balance
            assert _in_window(credit, receivable)
            similar = _strong_similarity(world, credit, customer_key(receivable))
            assert proposal.score == (75 if similar else 60)


@settings(deadline=None)
@given(engine_inputs(), st.randoms(use_true_random=False))
def test_the_engine_is_deterministic_and_ignores_input_order(
    world: EngineInput, rng: random.Random
) -> None:
    credits, receivables = list(world.credits), list(world.receivables)
    rng.shuffle(credits)
    rng.shuffle(receivables)
    shuffled = EngineInput(
        period=world.period,
        credits=tuple(credits),
        receivables=tuple(receivables),
        excluded=world.excluded,
    )

    assert run_engine(world) == run_engine(shuffled) == run_engine(world)


@settings(deadline=None)
@given(engine_inputs())
def test_proposals_respect_balances_and_never_reuse_anything(world: EngineInput) -> None:
    proposals = run_engine(world)

    available = {r.id: r.available_cents for r in world.receivables}
    used = Counter(
        item
        for proposal in proposals
        for item in (*proposal.credit_ids, *(a.receivable_id for a in proposal.applications))
    )
    assert all(count == 1 for count in used.values())
    for proposal in proposals:
        credits = sum(c.amount_cents for c in world.credits if c.id in proposal.credit_ids)
        applied = sum(a.applied_cents for a in proposal.applications)
        assert all(0 < a.applied_cents <= available[a.receivable_id] for a in proposal.applications)
        assert proposal.difference_cents == credits - applied
        assert (proposal.suggested_difference_reason is None) == (proposal.difference_cents == 0)
        assert 60 <= proposal.score <= 100


@settings(deadline=None)
@given(engine_inputs())
def test_every_proposal_meets_its_rule(world: EngineInput) -> None:
    for proposal in run_engine(world):
        _assert_rule_holds(world, proposal)


@settings(deadline=None)
@given(engine_inputs())
def test_excluded_combinations_are_never_proposed_again(world: EngineInput) -> None:
    first = run_engine(world)
    rerun = EngineInput(
        period=world.period,
        credits=world.credits,
        receivables=world.receivables,
        excluded=world.excluded | {proposal.key for proposal in first},
    )

    assert not {proposal.key for proposal in first} & world.excluded
    assert not {proposal.key for proposal in run_engine(rerun)} & rerun.excluded
