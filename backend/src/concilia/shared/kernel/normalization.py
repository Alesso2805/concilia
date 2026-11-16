import re
import unicodedata

from rapidfuzz import fuzz

DOC_REF_PATTERN = re.compile(r"\b([A-Z][A-Z0-9]{3}|[A-Z]\d{1,3})\s*-\s*0*(\d{1,8})\b")
SHORT_SERIES = re.compile(r"[A-Z]\d{1,3}")
NOT_ALPHANUMERIC = re.compile(r"[^A-Z0-9]+")
CORPORATE_SUFFIXES = frozenset({"SAC", "SA", "SAA", "SRL", "EIRL", "SCRL"})
MIN_NAME_WORD_LENGTH = 3
MIN_SINGLE_WORD_LENGTH = 5


def _upper_without_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.upper())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def normalize_text(text: str) -> str:
    return " ".join(NOT_ALPHANUMERIC.sub(" ", _upper_without_accents(text)).split())


def _doc_number(series: str, number: str) -> str:
    if SHORT_SERIES.fullmatch(series):
        series = series[0] + series[1:].rjust(3, "0")
    return f"{series}-{int(number)}"


def normalize_doc_number(raw: str) -> str | None:
    match = DOC_REF_PATTERN.fullmatch(_upper_without_accents(raw).strip())
    return None if match is None else _doc_number(match.group(1), match.group(2))


def extract_doc_refs(description: str) -> list[str]:
    refs = (
        _doc_number(match.group(1), match.group(2))
        for match in DOC_REF_PATTERN.finditer(_upper_without_accents(description))
    )
    return list(dict.fromkeys(refs))


def filtered_customer_name(customer_name_norm: str) -> str:
    return " ".join(
        word
        for word in customer_name_norm.split()
        if word not in CORPORATE_SUFFIXES and len(word) >= MIN_NAME_WORD_LENGTH
    )


def _contains_word(text: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", text) is not None


def customer_similarity(
    *, customer_name_norm: str, customer_tax_id: str | None, description_norm: str
) -> int:
    if customer_tax_id and _contains_word(description_norm, customer_tax_id):
        return 100
    name = filtered_customer_name(customer_name_norm)
    words = name.split()
    if not words:
        return 0
    if len(words) == 1:
        word = words[0]
        found = len(word) >= MIN_SINGLE_WORD_LENGTH and _contains_word(description_norm, word)
        return 100 if found else 0
    return int(fuzz.token_set_ratio(name, description_norm))
