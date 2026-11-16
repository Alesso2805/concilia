from dataclasses import replace
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from concilia.imports.domain.cells import Cell, Formula
from concilia.imports.domain.statement import (
    FileError,
    RowError,
    StatementLayout,
    StatementLine,
    fingerprints,
    read_statement,
)

ACCOUNT = UUID(int=7)
LAYOUT = StatementLayout(
    date="Fecha",
    description="Descripción",
    operation_number="Operación",
    amount="Monto",
    debit=None,
    credit=None,
    skip_rows=2,
    date_format="DD/MM/YYYY",
    decimal_separator=".",
    thousands_separator=",",
)
PREAMBLE: list[list[Cell]] = [["Banco de Prueba"], ["Cuenta 191-1234"]]
HEADER: list[Cell] = ["fecha", "DESCRIPCIÓN ", "Operación", "Monto", "Saldo"]


def test_lines_are_read_after_the_preamble_by_header_name() -> None:
    rows: list[list[Cell]] = [
        *PREAMBLE,
        HEADER,
        ["05/01/2027", "PAGO FACT F001-00000123", "000123", "1,180.00", "9,999.00"],
        [None, "", None, None],
        ["06/01/2027", "COMISION MANTENIMIENTO", None, "-12.50", ""],
    ]

    lines = read_statement(rows, LAYOUT)

    assert lines == [
        StatementLine(4, date(2027, 1, 5), 118_000, "PAGO FACT F001-00000123", "000123"),
        StatementLine(6, date(2027, 1, 6), -1_250, "COMISION MANTENIMIENTO", None),
    ]
    first = lines[0]
    assert isinstance(first, StatementLine)
    assert first.doc_refs == ["F001-123"]


def test_split_debit_and_credit_columns() -> None:
    layout = replace(LAYOUT, amount=None, debit="Cargo", credit="Abono", skip_rows=0)
    rows: list[list[Cell]] = [
        ["Fecha", "Descripción", "Operación", "Cargo", "Abono"],
        ["05/01/2027", "ABONO", "1", "", Decimal("500")],
        ["05/01/2027", "CARGO", "2", "-20.00", None],
        ["05/01/2027", "NADA", "3", "0", "0"],
    ]

    lines = read_statement(rows, layout)

    assert [(line.row_number, getattr(line, "amount_cents", None)) for line in lines] == [
        (2, 50_000),
        (3, -2_000),
        (4, None),
    ]
    assert lines[2] == RowError(4, "zero_amount", ("05/01/2027", "NADA", "3", "0", "0"))


def test_bad_rows_are_kept_with_their_reason() -> None:
    rows: list[list[Cell]] = [
        *PREAMBLE,
        HEADER,
        ["32/01/2027", "PAGO", None, "10.00"],
        ["05/01/2027", "", None, "10.00"],
        ["05/01/2027", "PAGO", None, Formula()],
    ]

    assert [
        (line.row_number, getattr(line, "code", None)) for line in read_statement(rows, LAYOUT)
    ] == [
        (4, "invalid_date"),
        (5, "missing_description"),
        (6, "formula_not_allowed"),
    ]


@pytest.mark.parametrize(
    ("rows", "code"),
    [
        ([["solo una fila"]], "missing_header"),
        ([*PREAMBLE, ["Fecha", "Monto"]], "missing_columns"),
        ([*PREAMBLE, HEADER], "no_rows"),
        ([*PREAMBLE, HEADER, *[["05/01/2027", "X", None, "1"]] * 10_001], "too_many_rows"),
    ],
)
def test_unreadable_files_fail_as_a_whole(rows: list[list[Cell]], code: str) -> None:
    with pytest.raises(FileError) as error:
        read_statement(rows, LAYOUT)
    assert error.value.code == code


lines = st.builds(
    StatementLine,
    row_number=st.just(1),
    booked_on=st.dates(min_value=date(2027, 1, 1), max_value=date(2027, 1, 31)),
    amount_cents=st.integers(min_value=-10_000, max_value=10_000).filter(bool),
    description=st.sampled_from(["PAGO F001-1", "pago  f001-1", "ABONO", "TRANSF"]),
    operation_number=st.none() | st.sampled_from(["1", "2"]),
)


@given(st.lists(lines, max_size=20))
def test_fingerprints_are_unique_within_a_file_and_stable_across_files(
    file: list[StatementLine],
) -> None:
    first = fingerprints(ACCOUNT, file)

    assert len(set(first)) == len(file)
    assert fingerprints(ACCOUNT, file) == first
    assert fingerprints(ACCOUNT, file[:1]) == first[:1]
    assert not set(fingerprints(UUID(int=8), file)) & set(first)


def test_identical_rows_differ_only_by_their_occurrence() -> None:
    line = StatementLine(1, date(2027, 1, 5), 10_000, "PAGO F001-1", None)
    same_text = replace(line, description="pago  F001-1")

    first, second = fingerprints(ACCOUNT, [line, line])

    assert first != second
    assert fingerprints(ACCOUNT, [same_text]) == [first]
