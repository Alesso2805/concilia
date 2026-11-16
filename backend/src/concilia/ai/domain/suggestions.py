from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from concilia.shared.kernel.normalization import customer_similarity

MAX_CANDIDATES = 10
MAX_SUGGESTIONS = 3
DIFFERENCE_REASONS = frozenset({"commission", "detraction", "rounding", "overpayment", "other"})


@dataclass(frozen=True)
class CreditFacts:
    id: UUID
    booked_on: date
    amount_cents: int
    description: str
    description_norm: str


@dataclass(frozen=True)
class OpenReceivable:
    id: UUID
    doc_number: str
    doc_number_norm: str
    customer_name: str
    customer_name_norm: str
    customer_tax_id: str | None
    issued_on: date
    due_on: date
    available_cents: int


@dataclass(frozen=True)
class Candidate:
    alias: str
    receivable: OpenReceivable


@dataclass(frozen=True)
class Proposal:
    """One suggestion as the model wrote it, after its shape was validated."""

    candidates: Sequence[str]
    applied: Sequence[tuple[str, int]] | None
    confidence: str
    explanation: str
    difference_reason: str | None


@dataclass(frozen=True)
class AppliedAmount:
    alias: str
    receivable_id: UUID
    applied_cents: int


@dataclass(frozen=True)
class ServerSuggestion:
    applied: list[AppliedAmount]
    difference_cents: int
    confidence: str
    explanation: str
    difference_reason: str | None
    recomputed: bool


def choose_candidates(
    credit: CreditFacts, receivables: Sequence[OpenReceivable]
) -> list[Candidate]:
    """Up to ten receivables with available balance, closest in amount, then most similar
    customer, then closest due date, then id; aliased C1 to C10 in that order."""

    def rank(receivable: OpenReceivable) -> tuple[int, int, int, int]:
        similarity = customer_similarity(
            customer_name_norm=receivable.customer_name_norm,
            customer_tax_id=receivable.customer_tax_id,
            description_norm=credit.description_norm,
        )
        return (
            abs(receivable.available_cents - credit.amount_cents),
            -similarity,
            abs((receivable.due_on - credit.booked_on).days),
            receivable.id.int,
        )

    ranked = sorted((r for r in receivables if r.available_cents > 0), key=rank)
    return [Candidate(f"C{n}", r) for n, r in enumerate(ranked[:MAX_CANDIDATES], start=1)]


def distribute(credit_cents: int, candidates: Sequence[Candidate]) -> list[AppliedAmount]:
    """Each candidate gets its whole available balance if they all fit in the credit;
    otherwise the credit is spread by due date and document number, and the last one reached
    gets what is left as a partial payment."""
    if sum(c.receivable.available_cents for c in candidates) <= credit_cents:
        ordered = list(candidates)
    else:
        ordered = sorted(
            candidates, key=lambda c: (c.receivable.due_on, c.receivable.doc_number_norm)
        )
    applied: list[AppliedAmount] = []
    left = credit_cents
    for candidate in ordered:
        cents = min(candidate.receivable.available_cents, left)
        if cents <= 0:
            break
        applied.append(AppliedAmount(candidate.alias, candidate.receivable.id, cents))
        left -= cents
    return applied


def recompute(
    credit_cents: int, proposal: Proposal, candidates: Mapping[str, Candidate]
) -> ServerSuggestion | None:
    """The server's version of one suggestion: aliases it did not send and amounts over the
    available balance are dropped; if the model gave no amounts or anything was dropped, the
    amounts are distributed by the server. None when no sent candidate remains."""
    sent = dict.fromkeys(proposal.candidates)
    chosen = [candidates[alias] for alias in sent if alias in candidates]
    if not chosen:
        return None
    dropped = len(chosen) != len(proposal.candidates)
    amounts: dict[str, int] = {}
    for alias, cents in proposal.applied or ():
        candidate = candidates.get(alias)
        valid = (
            candidate is not None
            and candidate in chosen
            and alias not in amounts
            and 0 < cents <= candidate.receivable.available_cents
        )
        if valid:
            amounts[alias] = cents
        else:
            dropped = True
    if proposal.applied is None or dropped or set(amounts) != {c.alias for c in chosen}:
        applied = distribute(credit_cents, chosen)
        recomputed = True
    else:
        applied = [AppliedAmount(c.alias, c.receivable.id, amounts[c.alias]) for c in chosen]
        recomputed = False
    difference = credit_cents - sum(item.applied_cents for item in applied)
    reason = proposal.difference_reason
    fits = reason in DIFFERENCE_REASONS and (reason != "overpayment" or difference > 0)
    if difference == 0 or not fits:
        reason = None
    return ServerSuggestion(
        applied, difference, proposal.confidence, proposal.explanation, reason, recomputed
    )


def recompute_all(
    credit_cents: int, proposals: Sequence[Proposal], candidates: Sequence[Candidate]
) -> list[ServerSuggestion]:
    by_alias = {candidate.alias: candidate for candidate in candidates}
    suggestions = (
        recompute(credit_cents, proposal, by_alias) for proposal in proposals[:MAX_SUGGESTIONS]
    )
    return [suggestion for suggestion in suggestions if suggestion is not None]
