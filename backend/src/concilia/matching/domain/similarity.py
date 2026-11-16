from collections import defaultdict
from collections.abc import Mapping, Sequence
from uuid import UUID

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
    # Bulk version of kernel customer_similarity, keeping only strong scores; a customer's
    # score is the best among its names. tests/unit/matching/test_similarity.py proves both agree.
    def __init__(self, credits: Sequence[Credit], receivables: Sequence[OpenReceivable]) -> None:
        self._by_credit: dict[UUID, dict[CustomerKey, int]] = defaultdict(dict)
        self._by_customer: dict[CustomerKey, dict[UUID, int]] = defaultdict(dict)
        names: dict[CustomerKey, set[str]] = defaultdict(set)
        tax_ids: dict[CustomerKey, str] = {}
        for receivable in receivables:
            key = customer_key(receivable)
            names[key].add(filtered_customer_name(receivable.customer_name_norm))
            if receivable.customer_tax_id:
                tax_ids[key] = receivable.customer_tax_id
        by_token: dict[str, list[UUID]] = defaultdict(list)
        for credit in credits:
            for token in dict.fromkeys(credit.description_norm.split()):
                by_token[token].append(credit.id)
        descriptions = [credit.description_norm for credit in credits]
        for key in sorted(names):
            found: dict[UUID, int] = {}
            if key in tax_ids:
                found.update(dict.fromkeys(by_token.get(tax_ids[key], ()), 100))
            for name in sorted(names[key]):
                words = name.split()
                if len(words) == 1 and len(name) >= MIN_SINGLE_WORD_LENGTH:
                    found.update(dict.fromkeys(by_token.get(name, ()), 100))
                elif len(words) > 1:
                    for _, score, index in process.extract(
                        name,
                        descriptions,
                        scorer=fuzz.token_set_ratio,
                        score_cutoff=STRONG_SIMILARITY,
                        limit=None,
                    ):
                        credit_id = credits[index].id
                        found[credit_id] = max(found.get(credit_id, 0), int(score))
            for credit_id, score in found.items():
                self._by_credit[credit_id][key] = score
                self._by_customer[key][credit_id] = score

    def similar_customers(self, credit_id: UUID) -> Mapping[CustomerKey, int]:
        return self._by_credit.get(credit_id, {})

    def similar_credits(self, customer: CustomerKey) -> Mapping[UUID, int]:
        return self._by_customer.get(customer, {})

    def similarity(self, credit_id: UUID, customer: CustomerKey) -> int | None:
        return self.similar_customers(credit_id).get(customer)
