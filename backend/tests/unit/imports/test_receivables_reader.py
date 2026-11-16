from datetime import date
from decimal import Decimal

import pytest

from concilia.imports.domain.cells import Cell
from concilia.imports.domain.receivables import ReceivableLine, ReceivablesLayout, read_receivables
from concilia.imports.domain.statement import FileError, RowError

LAYOUT = ReceivablesLayout(
    customer_name="Cliente",
    customer_tax_id="RUC",
    doc_number="Documento",
    issued_on="Emisión",
    due_on="Vencimiento",
    amount="Monto",
    skip_rows=0,
    date_format="DD/MM/YYYY",
    decimal_separator=".",
    thousands_separator=",",
)
HEADER: list[Cell] = ["Cliente", "RUC", "Documento", "Emisión", "Vencimiento", "Monto"]


def test_receivables_are_read_with_normalized_documents() -> None:
    rows: list[list[Cell]] = [
        HEADER,
        [
            "Comercial Andina S.A.C.",
            "20-51234567-8",
            "F001-00000123",
            "01/01/2027",
            "31/01/2027",
            "1,180.00",
        ],
        ["Gloria SA", "", "f1-124", "02/01/2027", "15/02/2027", Decimal("500")],
    ]

    lines = read_receivables(rows, LAYOUT)

    assert lines == [
        ReceivableLine(
            2,
            "Comercial Andina S.A.C.",
            "20512345678",
            "F001-00000123",
            "F001-123",
            date(2027, 1, 1),
            date(2027, 1, 31),
            118_000,
        ),
        ReceivableLine(
            3, "Gloria SA", None, "f1-124", "F001-124", date(2027, 1, 2), date(2027, 2, 15), 50_000
        ),
    ]
    first = lines[0]
    assert isinstance(first, ReceivableLine)
    assert first.customer_name_norm == "COMERCIAL ANDINA S A C"


@pytest.mark.parametrize(
    ("row", "code"),
    [
        (["", "", "F001-1", "01/01/2027", "31/01/2027", "1"], "missing_customer"),
        (["A", "", "", "01/01/2027", "31/01/2027", "1"], "missing_document"),
        (["A", "", "FACTURA 1", "01/01/2027", "31/01/2027", "1"], "invalid_document"),
        (["A", "123", "F001-1", "01/01/2027", "31/01/2027", "1"], "invalid_tax_id"),
        (["A", "", "F001-1", "31/01/2027", "01/01/2027", "1"], "due_before_issue"),
        (["A", "", "F001-1", "01/01/2027", "31/01/2027", "-5.00"], "non_positive_amount"),
        (["A", "", "F001-1", "01/01/2027", "31/01/2027", "0"], "non_positive_amount"),
        (["A", "", "F001-1", "01/13/2027", "31/01/2027", "1"], "invalid_date"),
    ],
)
def test_bad_receivable_rows_keep_their_reason(row: list[Cell], code: str) -> None:
    [line] = read_receivables([HEADER, row], LAYOUT)

    assert isinstance(line, RowError)
    assert (line.row_number, line.code) == (2, code)


def test_a_document_repeated_in_the_file_is_an_error_after_its_first_row() -> None:
    rows: list[list[Cell]] = [
        HEADER,
        ["A", "", "F001-00000001", "01/01/2027", "31/01/2027", "1"],
        ["B", "", "F1-1", "01/01/2027", "31/01/2027", "2"],
    ]

    lines = read_receivables(rows, LAYOUT)

    assert isinstance(lines[0], ReceivableLine)
    assert lines[1] == RowError(
        3, "repeated_document", ("B", "", "F1-1", "01/01/2027", "31/01/2027", "2")
    )


def test_the_tax_id_column_is_optional_in_the_layout() -> None:
    layout = ReceivablesLayout(**{**LAYOUT.__dict__, "customer_tax_id": None})
    rows: list[list[Cell]] = [
        ["Cliente", "Documento", "Emisión", "Vencimiento", "Monto"],
        ["A", "F001-1", "01/01/2027", "31/01/2027", "1"],
    ]

    [line] = read_receivables(rows, layout)

    assert isinstance(line, ReceivableLine)
    assert line.customer_tax_id is None


def test_missing_columns_fail_the_file() -> None:
    with pytest.raises(FileError) as error:
        read_receivables([["Cliente", "Monto"], ["A", "1"]], LAYOUT)
    assert error.value.code == "missing_columns"
