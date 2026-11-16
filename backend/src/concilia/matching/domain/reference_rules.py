from concilia.matching.domain import explanations
from concilia.matching.domain.amounts import detraction_rate, within_tolerance
from concilia.matching.domain.model import (
    Application,
    Credit,
    DifferenceReason,
    OpenReceivable,
    Rule,
)
from concilia.matching.domain.state import RunState

EXACT_SCORE = 100
SEVERAL_DOCUMENTS_SCORE = 95
REFERENCE_WITH_DIFFERENCE_SCORE = 85
MIN_DOCUMENTS = 2


def _mentioned(state: RunState, credit: Credit) -> list[OpenReceivable]:
    return [r for ref in credit.doc_refs if (r := state.free_receivable(ref)) is not None]


def _full(receivable: OpenReceivable) -> Application:
    return Application(receivable.id, receivable.available_cents)


def exact(state: RunState) -> None:
    for credit in state.free_credits():
        matching = [
            r for r in _mentioned(state, credit) if r.available_cents == credit.amount_cents
        ]
        if len(matching) == 1:
            receivable = matching[0]
            state.propose(
                rule=Rule.EXACT,
                score=EXACT_SCORE,
                credits=[credit],
                applications=[_full(receivable)],
                reason=None,
                explanation=explanations.exact(receivable.doc_number_norm),
            )


def several_documents(state: RunState) -> None:
    for credit in state.free_credits():
        mentioned = _mentioned(state, credit)
        if len(credit.doc_refs) < MIN_DOCUMENTS or len(mentioned) != len(credit.doc_refs):
            continue
        if sum(r.available_cents for r in mentioned) == credit.amount_cents:
            state.propose(
                rule=Rule.SEVERAL_DOCUMENTS,
                score=SEVERAL_DOCUMENTS_SCORE,
                credits=[credit],
                applications=[_full(r) for r in mentioned],
                reason=None,
                explanation=explanations.several_documents([r.doc_number_norm for r in mentioned]),
            )


def _explained_difference(
    state: RunState, credit: Credit, receivable: OpenReceivable
) -> tuple[DifferenceReason, str] | None:
    balance = receivable.available_cents
    difference = credit.amount_cents - balance
    document = receivable.doc_number_norm
    if within_tolerance(difference, balance, state.policy):
        return DifferenceReason.ROUNDING, explanations.within_tolerance(document, difference)
    rate = detraction_rate(credit.amount_cents, balance, state.policy)
    if rate is not None:
        return DifferenceReason.DETRACTION, explanations.detraction(document, difference, rate)
    return None


def reference_with_difference(state: RunState) -> None:
    for credit in state.free_credits():
        matching = [
            (receivable, explained)
            for receivable in _mentioned(state, credit)
            if (explained := _explained_difference(state, credit, receivable)) is not None
        ]
        if len(matching) == 1:
            receivable, (reason, explanation) = matching[0]
            state.propose(
                rule=Rule.REFERENCE_WITH_DIFFERENCE,
                score=REFERENCE_WITH_DIFFERENCE_SCORE,
                credits=[credit],
                applications=[_full(receivable)],
                reason=reason,
                explanation=explanation,
            )
