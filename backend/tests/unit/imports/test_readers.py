import io
import zipfile
from datetime import datetime
from decimal import Decimal

import pytest
from defusedxml import EntitiesForbidden
from openpyxl import Workbook, load_workbook

from concilia.imports.domain.cells import Formula
from concilia.imports.domain.statement import FileError, StatementLayout, read_statement
from concilia.imports.infrastructure.readers import (
    MAX_FILE_BYTES,
    detect_format,
    read_csv,
    read_rows,
    read_xlsx,
)

XXE = '<!DOCTYPE workbook [<!ENTITY secret SYSTEM "file:///etc/passwd">]>'


def _xlsx(rows: list[list[object]], title: str = "Movimientos") -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = title
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _replace_part(content: bytes, name: str, data: str) -> bytes:
    source = zipfile.ZipFile(io.BytesIO(content))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as target:
        for entry in source.infolist():
            target.writestr(entry, data if entry.filename == name else source.read(entry))
    return buffer.getvalue()


def _error(call: object) -> str:
    assert callable(call)
    with pytest.raises(FileError) as error:
        call()
    return error.value.code


def test_xlsx_cells_keep_their_types_without_floats_or_formulas() -> None:
    content = _xlsx(
        [
            ["Fecha", "Descripción", "Monto"],
            [datetime(2027, 1, 5), "PAGO F001-1", 1180.5],  # noqa: DTZ001 - Excel dates are naive
            ["06/01/2027", "COMISION", -12],
            ["07/01/2027", "TOTAL", "=SUM(C2:C3)"],
        ]
    )

    rows = read_xlsx(content, None, 0)

    assert rows[1] == [datetime(2027, 1, 5), "PAGO F001-1", Decimal("1180.5")]  # noqa: DTZ001
    assert rows[2][2] == Decimal(-12)
    assert rows[3][2] == Formula()


def test_a_named_sheet_is_required_to_exist() -> None:
    content = _xlsx([["Fecha"]], title="Hoja1")

    assert read_xlsx(content, "Hoja1", 0) == [["Fecha"]]
    assert _error(lambda: read_xlsx(content, "Movimientos", 0)) == "missing_sheet"


def test_xml_entities_are_refused_by_defusedxml() -> None:
    base = _xlsx([["Fecha"]])
    workbook_xml = zipfile.ZipFile(io.BytesIO(base)).read("xl/workbook.xml").decode()
    content = _replace_part(base, "xl/workbook.xml", XXE + workbook_xml)

    with pytest.raises(ValueError, match="Unable to read workbook") as error:
        load_workbook(io.BytesIO(content), read_only=True)
    assert isinstance(error.value.__cause__ or error.value.__context__, EntitiesForbidden)
    assert _error(lambda: read_xlsx(content, None, 0)) == "unreadable_file"


def test_csv_with_bom_semicolons_and_latin_1() -> None:
    utf8 = "﻿Fecha;Descripción;Monto\r\n05/01/2027;PAGO;1.180,50\r\n".encode()
    latin = "Fecha,Descripción\n05/01/2027,ACEÑA\n".encode("latin-1")

    assert read_csv(utf8, "utf-8", ";", 0) == [
        ["Fecha", "Descripción", "Monto"],
        ["05/01/2027", "PAGO", "1.180,50"],
    ]
    assert read_csv(latin, "latin-1", ",", 0)[1] == ["05/01/2027", "ACEÑA"]
    assert _error(lambda: read_csv(latin, "utf-8", ",", 0)) == "wrong_encoding"


def test_too_many_rows_stop_the_reader_early() -> None:
    content = ("Fecha\n" + "05/01/2027\n" * 10_001).encode()

    assert _error(lambda: read_csv(content, "utf-8", ",", 0)) == "too_many_rows"
    assert len(read_csv(content, "utf-8", ",", 1)) == 10_002


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"", "empty_file"),
        (b"Fecha\x00Monto", "unreadable_file"),
        (b"PK\x03\x04 not really a zip", "unreadable_file"),
        (b"x" * (MAX_FILE_BYTES + 1), "file_too_large"),
    ],
)
def test_content_decides_what_a_file_is(content: bytes, code: str) -> None:
    assert _error(lambda: detect_format(content)) == code


def test_a_zip_that_is_not_a_workbook_is_refused() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "hola")

    assert _error(lambda: detect_format(buffer.getvalue())) == "unreadable_file"


def test_the_profile_format_must_match_the_content() -> None:
    xlsx = _xlsx([["Fecha"]])

    assert detect_format(xlsx) == "xlsx"
    assert detect_format(b"Fecha,Monto\n") == "csv"
    assert (
        _error(
            lambda: read_rows(
                xlsx, expected="csv", sheet=None, encoding="utf-8", delimiter=",", skip_rows=0
            )
        )
        == "wrong_format"
    )


def test_a_bank_style_workbook_becomes_statement_lines() -> None:
    content = _xlsx(
        [
            ["Banco de Prueba"],
            ["Movimientos de la cuenta"],
            [],
            [],
            ["Fecha", "Descripción operación", "Monto", "Operación - Número"],
            ["05/01/2027", "PAGO FACT F001-123", 1180, "000123"],
            ["06/01/2027", "COMISION", -12.5, None],
        ]
    )
    layout = StatementLayout(
        date="Fecha",
        description="Descripción operación",
        operation_number="Operación - Número",
        amount="Monto",
        debit=None,
        credit=None,
        skip_rows=4,
        date_format="DD/MM/YYYY",
        decimal_separator=".",
        thousands_separator="",
    )

    rows = read_rows(
        content, expected="xlsx", sheet=None, encoding="utf-8", delimiter=",", skip_rows=4
    )
    lines = read_statement(rows, layout)

    assert [(getattr(line, "amount_cents", None), line.row_number) for line in lines] == [
        (118_000, 6),
        (-1_250, 7),
    ]
