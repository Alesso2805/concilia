from collections import defaultdict
from collections.abc import Mapping, Sequence

from rapidfuzz import fuzz, process

from concilia.matching.domain.model import Credit, OpenReceivable
from concilia.shared.kernel.normalization import MIN_SINGLE_WORD_LENGTH, filtered_customer_name

STRONG_SIMILARITY = 85

type CustomerKey = str


def customer_key(receivable: OpenReceivable) -> CustomerKey:
    if receivable.customer_tax_id:
        return f"ruc:{receivable.customer_tax_id}"
    return f"name:{receivable.customer_name_norm}"


class SimilarityIndex:
    # Bulk version of kernel customer_similarity that keeps only strong scores (a customer
    # scores its best name); test_similarity.py proves both agree. Credits are keyed by
    # UUID.int because hashing UUID objects dominated large runs.
    def __init__(self, credits: Sequence[Credit], receivables: Sequence[OpenReceivable]) -> None:
        self._scores: defaultdict[int, dict[CustomerKey, int]] = defaultdict(dict)
        self._credits: defaultdict[CustomerKey, list[Credit]] = defaultdict(list)
        names: dict[CustomerKey, set[str]] = defaultdict(set)
        tax_ids: dict[CustomerKey, str] = {}
        for receivable in receivables:
            key = customer_key(receivable)
            names[key].add(filtered_customer_name(receivable.customer_name_norm))
            if receivable.customer_tax_id:
                tax_ids[key] = receivable.customer_tax_id
        by_token: defaultdict[str, list[int]] = defaultdict(list)
        for position, credit in enumerate(credits):
            for token in dict.fromkeys(credit.description_norm.split()):
                by_token[token].append(position)
        descriptions = [credit.description_norm for credit in credits]
        for key in sorted(names):
            found: dict[int, int] = {}
            if key in tax_ids:
                found.update(dict.fromkeys(by_token.get(tax_ids[key], ()), 100))
            for name in sorted(names[key]):
                words = name.split()
                if len(words) == 1 and len(name) >= MIN_SINGLE_WORD_LENGTH:
                    found.update(dict.fromkeys(by_token.get(name, ()), 100))
                elif len(words) > 1:
                    for _, score, position in process.extract(
                        name,
                        descriptions,
                        scorer=fuzz.token_set_ratio,
                        score_cutoff=STRONG_SIMILARITY,
                        limit=None,
                    ):
                        found[position] = max(found.get(position, 0), int(score))
            for position in sorted(found):
                credit = credits[position]
                self._scores[credit.id.int][key] = found[position]
                self._credits[key].append(credit)

    def similar_customers(self, credit: Credit) -> Mapping[CustomerKey, int]:
        return self._scores.get(credit.id.int, {})

    def similar_credits(self, customer: CustomerKey) -> Sequence[Credit]:
        return self._credits.get(customer, [])

    def similarity(self, credit: Credit, customer: CustomerKey) -> int | None:
        return self.similar_customers(credit).get(customer)
