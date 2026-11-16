from hypothesis import given
from hypothesis import strategies as st

from concilia.matching.domain.similarity import STRONG_SIMILARITY, SimilarityIndex, customer_key
from concilia.shared.kernel.normalization import customer_similarity
from tests.support.engine import credit, receivable

WORDS = ["COMERCIAL", "ANDINA", "ANDINAS", "ANDES", "GLORIA", "GLORIANA", "LIMA", "SAC", "SA", "DE"]
TAX_IDS = ["20512345678", "20100047218"]

names = st.lists(st.sampled_from(WORDS), max_size=4).map(" ".join)
descriptions = st.lists(st.sampled_from([*WORDS, *TAX_IDS, "TRANSF", "F001-1"]), max_size=6).map(
    " ".join
)
customers = st.tuples(names, st.none() | st.sampled_from(TAX_IDS))


def test_customer_key_prefers_the_tax_id() -> None:
    assert customer_key(receivable("F001-1", 1, tax_id="20512345678")) == "ruc:20512345678"
    assert customer_key(receivable("F001-1", 1)) == "name:COMERCIAL ANDINA SAC"


@given(st.lists(customers, min_size=1, max_size=6), st.lists(descriptions, max_size=6))
def test_index_agrees_with_customer_similarity(
    customer_list: list[tuple[str, str | None]], description_list: list[str]
) -> None:
    receivables = [
        receivable(f"F001-{n}", 1, customer=name, tax_id=tax_id)
        for n, (name, tax_id) in enumerate(customer_list)
    ]
    credits = [credit(n, 1, description) for n, description in enumerate(description_list)]

    index = SimilarityIndex(credits, receivables)

    for paid in credits:
        best: dict[str, int] = {}
        for r in receivables:
            score = customer_similarity(
                customer_name_norm=r.customer_name_norm,
                customer_tax_id=r.customer_tax_id,
                description_norm=paid.description_norm,
            )
            best[customer_key(r)] = max(best.get(customer_key(r), 0), score)
        strong = {key: score for key, score in best.items() if score >= STRONG_SIMILARITY}
        assert dict(index.similar_customers(paid.id)) == strong
        for key, score in strong.items():
            assert index.similar_credits(key)[paid.id] == score
