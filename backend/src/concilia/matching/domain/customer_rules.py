from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from datetime import timedelta
from itertools import combinations
from math import comb

from concilia.matching.domain import explanations
from concilia.matching.domain.model import Credit, OpenReceivable, Rule
from concilia.matching.domain.similarity import customer_key
from concilia.matching.domain.state import RunState

SAME_CUSTOMER_SCORE = 80
PAID_IN_PARTS_SCORE = 75
AMOUNT_AND_DATE_SCORE = 60
SIMILAR_CUSTOMER_BONUS = 15
SAME_CUSTOMER_NEAREST = 10
SAME_CUSTOMER_SIZES = range(2, 5)
PAID_IN_PARTS_NEAREST = 12
PAID_IN_PARTS_SIZES = range(2, 4)
PAID_IN_PARTS_MAX_SPREAD = timedelta(days=30)
DAYS_AFTER_DUE = timedelta(days=30)
MAX_COMBINATIONS = 500


def in_payment_window(credit: Credit, receivable: OpenReceivable) -> bool:
    return receivable.issued_on <= credit.booked_on <= receivable.due_on + DAYS_AFTER_DUE


def unique_combination[T](
    items: Sequence[T],
    sizes: range,
    total: int,
    amount: Callable[[T], int],
    accept: Callable[[tuple[T, ...]], bool] = lambda _: True,
) -> tuple[T, ...] | None:
    if sum(comb(len(items), size) for size in sizes) > MAX_COMBINATIONS:
        return None
    found = None
    for size in sizes:
        for combination in combinations(items, size):
            if sum(map(amount, combination)) == total and accept(combination):
                if found is not None:
                    return None
                found = combination
    return found


def same_customer(state: RunState) -> None:
    for credit in state.free_credits():
        scores = state.similarity.similar_customers(credit.id)
        if not scores:
            continue
        best = max(scores.values())
        leaders = [customer for customer, score in scores.items() if score == best]
        if len(leaders) != 1:
            continue
        nearest = sorted(
            filter(state.is_free, state.receivables_of(leaders[0])),
            key=lambda r: (abs((r.due_on - credit.booked_on).days), r.due_on, r.id),
        )[:SAME_CUSTOMER_NEAREST]
        found = unique_combination(
            nearest, SAME_CUSTOMER_SIZES, credit.amount_cents, lambda r: r.available_cents
        )
        if found is None:
            continue
        receivables = sorted(found, key=lambda r: (r.due_on, r.id))
        state.propose(
            rule=Rule.SAME_CUSTOMER,
            score=SAME_CUSTOMER_SCORE,
            credits=[credit],
            applications=[r.full_application() for r in receivables],
            reason=None,
            explanation=explanations.same_customer([r.doc_number_norm for r in receivables], best),
        )


def _within_spread(credits: tuple[Credit, ...]) -> bool:
    dates = [credit.booked_on for credit in credits]
    return max(dates) - min(dates) <= PAID_IN_PARTS_MAX_SPREAD


def paid_in_parts(state: RunState) -> None:
    for receivable in state.free_receivables():
        similar = state.similarity.similar_credits(customer_key(receivable))
        candidates = [
            credit
            for credit in map(state.credit, similar)
            if state.is_free(credit) and in_payment_window(credit, receivable)
        ]
        nearest = sorted(
            candidates,
            key=lambda c: (abs((c.booked_on - receivable.due_on).days), c.booked_on, c.id),
        )[:PAID_IN_PARTS_NEAREST]
        found = unique_combination(
            nearest,
            PAID_IN_PARTS_SIZES,
            receivable.available_cents,
            lambda c: c.amount_cents,
            _within_spread,
        )
        if found is None:
            continue
        credits = sorted(found, key=lambda c: (c.booked_on, c.id))
        state.propose(
            rule=Rule.PAID_IN_PARTS,
            score=PAID_IN_PARTS_SCORE,
            credits=credits,
            applications=[receivable.full_application()],
            reason=None,
            explanation=explanations.paid_in_parts(
                receivable.doc_number_norm,
                len(credits),
                credits[0].booked_on,
                credits[-1].booked_on,
            ),
        )


def amount_and_date(state: RunState) -> None:
    by_amount: defaultdict[int, list[OpenReceivable]] = defaultdict(list)
    for receivable in state.free_receivables():
        by_amount[receivable.available_cents].append(receivable)
    credits = list(state.free_credits())
    candidates = {
        credit.id: [r for r in by_amount[credit.amount_cents] if in_payment_window(credit, r)]
        for credit in credits
    }
    claims = Counter(r.id for found in candidates.values() for r in found)
    unique_pairs: list[tuple[Credit, OpenReceivable, int | None]] = []
    for credit in credits:
        found = candidates[credit.id]
        if len(found) == 1 and claims[found[0].id] == 1:
            similarity = state.similarity.similarity(credit.id, customer_key(found[0]))
            unique_pairs.append((credit, found[0], similarity))
    unique_pairs.sort(key=lambda pair: (pair[2] is None, pair[0].booked_on, pair[0].id))
    for credit, receivable, similarity in unique_pairs:
        bonus = 0 if similarity is None else SIMILAR_CUSTOMER_BONUS
        state.propose(
            rule=Rule.AMOUNT_AND_DATE,
            score=AMOUNT_AND_DATE_SCORE + bonus,
            credits=[credit],
            applications=[receivable.full_application()],
            reason=None,
            explanation=explanations.amount_and_date(receivable.doc_number_norm, similarity),
        )
