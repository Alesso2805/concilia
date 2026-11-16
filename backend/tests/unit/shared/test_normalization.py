import pytest
from hypothesis import given
from hypothesis import strategies as st

from concilia.shared.kernel.normalization import (
    customer_similarity,
    extract_doc_refs,
    filtered_customer_name,
    normalize_doc_number,
    normalize_text,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Pagó  factura N° 123", "PAGO FACTURA N 123"),
        ("  Compañía   Peña S.A.C. ", "COMPANIA PENA S A C"),
        ("transf. cliente ABC", "TRANSF CLIENTE ABC"),
        ("D'Onofrio", "D ONOFRIO"),
        ("", ""),
    ],
)
def test_normalize_text(raw: str, expected: str) -> None:
    assert normalize_text(raw) == expected


@given(st.text())
def test_normalize_text_is_idempotent(raw: str) -> None:
    once = normalize_text(raw)

    assert normalize_text(once) == once
    assert all(char.isascii() and (char.isalnum() or char == " ") for char in once)
    assert "  " not in once


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("F001-00000123", "F001-123"),
        ("F1-123", "F001-123"),
        ("f001-123", "F001-123"),
        ("F01 - 123", "F001-123"),
        ("E001-0", "E001-0"),
        ("FA01-77", "FA01-77"),
        ("B12-45", "B012-45"),
        ("001-123", None),
        ("F0001-123", None),
        ("F001-123456789", None),
        ("FACTURA 123", None),
    ],
)
def test_normalize_doc_number(raw: str, expected: str | None) -> None:
    assert normalize_doc_number(raw) == expected


@given(
    series=st.from_regex(r"[A-Z][A-Z0-9]{3}|[A-Z][0-9]{1,3}", fullmatch=True),
    zeros=st.integers(0, 4),
    number=st.integers(0, 99_999_999),
)
def test_normalized_doc_numbers_are_fixed_points(series: str, zeros: int, number: int) -> None:
    digits = str(number)
    raw = f"{series}-{'0' * min(zeros, 8 - len(digits))}{digits}"

    normalized = normalize_doc_number(raw)

    assert normalized is not None
    assert normalize_doc_number(normalized) == normalized
    assert extract_doc_refs(f"PAGO {raw} GRACIAS") == [normalized]


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("PAGO FACT F001-00000123", ["F001-123"]),
        ("Pagó fact.F1-123 y f001 - 124", ["F001-123", "F001-124"]),
        ("ABONO F001-123 F001-0123", ["F001-123"]),
        ("transf. cliente ABC", []),
        ("OPERACION 123456-789012", []),
        ("REF FF001-123", []),
    ],
)
def test_extract_doc_refs(description: str, expected: list[str]) -> None:
    assert extract_doc_refs(description) == expected


def test_filtered_customer_name_drops_suffixes_and_short_words() -> None:
    assert filtered_customer_name("COMERCIAL DE LA COSTA S A C") == "COMERCIAL COSTA"
    assert filtered_customer_name("ACME SAC") == "ACME"
    assert filtered_customer_name("EL SA") == ""


@pytest.mark.parametrize(
    ("name", "tax_id", "description", "expected"),
    [
        ("NADA QUE VER SAC", "20512345678", "TRANSF 20512345678 PAGO", 100),
        ("COMERCIAL ANDINA SAC", None, "PAGO COMERCIAL ANDINA FACT", 100),
        ("GLORIA SA", None, "ABONO GLORIA ENERO", 100),
        ("ACME SAC", None, "PAGO ACME", 0),
        ("EL SA", None, "PAGO EL SA", 0),
    ],
)
def test_customer_similarity_examples(
    name: str, tax_id: str | None, description: str, expected: int
) -> None:
    assert (
        customer_similarity(
            customer_name_norm=name, customer_tax_id=tax_id, description_norm=description
        )
        == expected
    )


@pytest.mark.parametrize(
    ("name", "tax_id", "description"),
    [
        ("GLORIA SA", None, "ABONO GLORIANA ENERO"),
        ("DISTRIBUIDORA NORTE SAC", None, "TRANSF DISTRIBUIDORA SUR"),
        ("NADA QUE VER SAC", "20512345678", "TRANSF 205123456789 PAGO"),
        ("PANIFICADORA LIMA SAC", None, "PAGO PROVEEDOR LIMA NORTE"),
    ],
)
def test_customer_similarity_rejects_false_positives(
    name: str, tax_id: str | None, description: str
) -> None:
    score = customer_similarity(
        customer_name_norm=name, customer_tax_id=tax_id, description_norm=description
    )

    assert score < 85


@given(st.text(), st.text())
def test_customer_similarity_is_an_integer_score(name: str, description: str) -> None:
    score = customer_similarity(
        customer_name_norm=normalize_text(name),
        customer_tax_id=None,
        description_norm=normalize_text(description),
    )

    assert isinstance(score, int)
    assert 0 <= score <= 100
