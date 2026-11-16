from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from concilia.banking.domain.model import ProfileKind

ColumnName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class FileFormat(StrEnum):
    CSV = "csv"
    XLSX = "xlsx"


class DateFormat(StrEnum):
    DAY_MONTH_YEAR = "DD/MM/YYYY"
    DAY_MONTH_YEAR_DASH = "DD-MM-YYYY"
    DAY_MONTH_SHORT_YEAR = "DD/MM/YY"
    ISO = "YYYY-MM-DD"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _distinct(columns: _Strict) -> None:
    names = [name.casefold() for name in columns.model_dump().values() if name is not None]
    if len(names) != len(set(names)):
        raise ValueError("each field needs its own column")


class StatementColumns(_Strict):
    date: ColumnName
    description: ColumnName
    operation_number: ColumnName | None = None
    amount: ColumnName | None = None
    debit: ColumnName | None = None
    credit: ColumnName | None = None

    @model_validator(mode="after")
    def _one_amount_layout(self) -> Self:
        signed = self.amount is not None
        split = self.debit is not None and self.credit is not None
        if signed == split or (not split and (self.debit or self.credit)):
            raise ValueError("use either a signed amount column or both debit and credit")
        _distinct(self)
        return self


class ReceivablesColumns(_Strict):
    customer_name: ColumnName
    customer_tax_id: ColumnName | None = None
    doc_number: ColumnName
    issued_on: ColumnName
    due_on: ColumnName
    amount: ColumnName

    @model_validator(mode="after")
    def _distinct_columns(self) -> Self:
        _distinct(self)
        return self


class _FileLayout(_Strict):
    version: Literal[1] = 1
    format: FileFormat
    sheet: Annotated[str, StringConstraints(min_length=1, max_length=31)] | None = None
    encoding: Literal["utf-8", "latin-1"] = "utf-8"
    delimiter: Literal[",", ";", "\t", "|"] = ","
    skip_rows: int = Field(default=0, ge=0, le=50)
    date_format: DateFormat
    decimal_separator: Literal[".", ","] = "."
    thousands_separator: Literal["", ",", ".", " "] = ""

    @model_validator(mode="after")
    def _consistent_layout(self) -> Self:
        if self.decimal_separator == self.thousands_separator:
            raise ValueError("the decimal and thousands separators must differ")
        if self.format == FileFormat.CSV and self.sheet is not None:
            raise ValueError("only Excel files have sheets")
        return self


class StatementConfig(_FileLayout):
    columns: StatementColumns


class ReceivablesConfig(_FileLayout):
    columns: ReceivablesColumns


type ProfileConfig = StatementConfig | ReceivablesConfig

CONFIG_MODELS: dict[ProfileKind, type[StatementConfig] | type[ReceivablesConfig]] = {
    ProfileKind.BANK_STATEMENT: StatementConfig,
    ProfileKind.RECEIVABLES: ReceivablesConfig,
}


def parse_config(kind: ProfileKind, raw: Any) -> ProfileConfig:
    return CONFIG_MODELS[kind].model_validate(raw)
