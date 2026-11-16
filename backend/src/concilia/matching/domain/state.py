from collections import defaultdict
from collections.abc import Iterator, Sequence
from functools import cached_property

from concilia.matching.domain.model import (
    Application,
    Credit,
    DifferenceReason,
    EngineInput,
    MatchKey,
    OpenReceivable,
    Proposal,
    Rule,
)
from concilia.matching.domain.similarity import CustomerKey, SimilarityIndex, customer_key


class RunState:
    def __init__(self, engine_input: EngineInput) -> None:
        self.input = engine_input
        self.policy = engine_input.policy
        self.credits = tuple(sorted(engine_input.credits, key=lambda c: (c.booked_on, c.id)))
        self.receivables = tuple(sorted(engine_input.receivables, key=lambda r: (r.due_on, r.id)))
        self.proposals: list[Proposal] = []
        self._by_document = {r.doc_number_norm: r for r in self.receivables}
        self._by_customer: defaultdict[CustomerKey, list[OpenReceivable]] = defaultdict(list)
        for receivable in self.receivables:
            self._by_customer[customer_key(receivable)].append(receivable)
        # UUID.int keys: hashing UUID objects dominated large runs.
        self._used: set[int] = set()

    @cached_property
    def similarity(self) -> SimilarityIndex:
        return SimilarityIndex(self.credits, self.receivables)

    def receivables_of(self, customer: CustomerKey) -> Sequence[OpenReceivable]:
        return self._by_customer.get(customer, [])

    def is_free(self, item: Credit | OpenReceivable) -> bool:
        return item.id.int not in self._used

    def free_credits(self) -> Iterator[Credit]:
        return (credit for credit in self.credits if self.is_free(credit))

    def free_receivables(self) -> Iterator[OpenReceivable]:
        return (receivable for receivable in self.receivables if self.is_free(receivable))

    def free_receivable(self, document: str) -> OpenReceivable | None:
        receivable = self._by_document.get(document)
        return receivable if receivable is not None and self.is_free(receivable) else None

    def propose(
        self,
        *,
        rule: Rule,
        score: int,
        credits: Sequence[Credit],
        applications: Sequence[Application],
        reason: DifferenceReason | None,
        explanation: str,
    ) -> None:
        credit_ids = tuple(credit.id for credit in credits)
        receivable_ids = frozenset(application.receivable_id for application in applications)
        if MatchKey(frozenset(credit_ids), receivable_ids) in self.input.excluded:
            return
        difference = sum(c.amount_cents for c in credits) - sum(
            application.applied_cents for application in applications
        )
        self._used.update(item.int for item in (*credit_ids, *receivable_ids))
        self.proposals.append(
            Proposal(
                rule=rule,
                score=score,
                credit_ids=credit_ids,
                applications=tuple(applications),
                difference_cents=difference,
                suggested_difference_reason=reason if difference else None,
                explanation=explanation,
            )
        )
