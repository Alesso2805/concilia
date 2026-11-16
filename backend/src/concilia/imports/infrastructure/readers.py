import csv
import io
import zipfile
from datetime import date
from decimal import Decimal
from typing import Literal

from openpyxl import load_workbook
from openpyxl.xml import DEFUSEDXML

from concilia.imports.domain.cells import Cell, Formula
from concilia.imports.domain.statement import MAX_ROWS, FileError

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 60 * 1024 * 1024
MAX_COLUMNS = 60
ZIP_MAGIC = b"PK\x03\x04"
XLSX_PARTS = frozenset({"[Content_Types].xml", "xl/workbook.xml"})

if not DEFUSEDXML:
    raise ImportError("openpyxl must find defusedxml to parse workbooks safely")

type FileFormat = Literal["csv", "xlsx"]


def detect_format(content: bytes) -> FileFormat:
    if not content:
        raise FileError("empty_file")
    if len(content) > MAX_FILE_BYTES:
        raise FileError("file_too_large")
    if content.startswith(ZIP_MAGIC):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                entries = archive.infolist()
        except zipfile.BadZipFile:
            raise FileError("unreadable_file") from None
        if not {entry.filename for entry in entries} >= XLSX_PARTS:
            raise FileError("unreadable_file")
        if sum(entry.file_size for entry in entries) > MAX_UNCOMPRESSED_BYTES:
            raise FileError("file_too_large")
        return "xlsx"
    if b"\x00" in content:
        raise FileError("unreadable_file")
    return "csv"


def _limit(rows_read: int, skip_rows: int) -> None:
    if rows_read > MAX_ROWS + skip_rows + 1:
        raise FileError("too_many_rows")


def read_csv(content: bytes, encoding: str, delimiter: str, skip_rows: int) -> list[list[Cell]]:
    try:
        text = content.decode("utf-8-sig" if encoding == "utf-8" else encoding)
    except UnicodeDecodeError:
        raise FileError("wrong_encoding") from None
    rows: list[list[Cell]] = []
    try:
        for row in csv.reader(io.StringIO(text, newline=""), delimiter=delimiter):
            rows.append(list(row[:MAX_COLUMNS]))
            _limit(len(rows), skip_rows)
    except csv.Error:
        raise FileError("unreadable_file") from None
    return rows


def _cell(value: object, data_type: str) -> Cell:
    if data_type == "f":
        return Formula()
    if value is None or isinstance(value, str | date):
        return value
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    return str(value)


def read_xlsx(content: bytes, sheet: str | None, skip_rows: int) -> list[list[Cell]]:
    try:
        workbook = load_workbook(
            io.BytesIO(content), read_only=True, data_only=False, keep_links=False
        )
    except Exception:
        raise FileError("unreadable_file") from None
    try:
        if sheet is not None and sheet not in workbook.sheetnames:
            raise FileError("missing_sheet")
        worksheet = workbook[sheet] if sheet is not None else workbook.worksheets[0]
        rows: list[list[Cell]] = []
        for row in worksheet.iter_rows(max_col=MAX_COLUMNS):
            cells = [_cell(cell.value, getattr(cell, "data_type", "n")) for cell in row]
            while cells and cells[-1] is None:
                cells.pop()
            rows.append(cells)
            _limit(len(rows), skip_rows)
        return rows
    finally:
        workbook.close()


def read_rows(
    content: bytes,
    *,
    expected: FileFormat,
    sheet: str | None,
    encoding: str,
    delimiter: str,
    skip_rows: int,
) -> list[list[Cell]]:
    if detect_format(content) != expected:
        raise FileError("wrong_format")
    if expected == "xlsx":
        return read_xlsx(content, sheet, skip_rows)
    return read_csv(content, encoding, delimiter, skip_rows)
