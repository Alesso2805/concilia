from dataclasses import dataclass

from concilia.banking.application.profile_config import (
    DateFormat,
    FileFormat,
    ProfileConfig,
    ReceivablesColumns,
    ReceivablesConfig,
    StatementColumns,
    StatementConfig,
)
from concilia.banking.domain.model import ProfileKind


@dataclass(frozen=True)
class Template:
    key: str
    name: str
    bank: str | None
    kind: ProfileKind
    config: ProfileConfig


# Column names follow each bank's online-banking Excel export as publicly documented; banks
# change them without notice, so the interface tells users to check them against a real file.
TEMPLATES: tuple[Template, ...] = (
    Template(
        "bcp",
        "BCP · movimientos en Excel",
        "BCP",
        ProfileKind.BANK_STATEMENT,
        StatementConfig(
            format=FileFormat.XLSX,
            skip_rows=4,
            date_format=DateFormat.DAY_MONTH_YEAR,
            columns=StatementColumns(
                date="Fecha",
                description="Descripción operación",
                operation_number="Operación - Número",
                amount="Monto",
            ),
        ),
    ),
    Template(
        "interbank",
        "Interbank · movimientos en Excel",
        "Interbank",
        ProfileKind.BANK_STATEMENT,
        StatementConfig(
            format=FileFormat.XLSX,
            skip_rows=6,
            date_format=DateFormat.DAY_MONTH_YEAR,
            columns=StatementColumns(
                date="Fecha de operación",
                description="Descripción",
                operation_number="Nro. de operación",
                debit="Cargo",
                credit="Abono",
            ),
        ),
    ),
    Template(
        "bbva",
        "BBVA · movimientos en Excel",
        "BBVA",
        ProfileKind.BANK_STATEMENT,
        StatementConfig(
            format=FileFormat.XLSX,
            skip_rows=5,
            date_format=DateFormat.DAY_MONTH_YEAR,
            decimal_separator=",",
            thousands_separator=".",
            columns=StatementColumns(
                date="F. Operación",
                description="Concepto",
                operation_number="Nº. Doc.",
                amount="Importe",
            ),
        ),
    ),
    Template(
        "receivables",
        "Cobros esperados · CSV genérico",
        None,
        ProfileKind.RECEIVABLES,
        ReceivablesConfig(
            format=FileFormat.CSV,
            date_format=DateFormat.DAY_MONTH_YEAR,
            columns=ReceivablesColumns(
                customer_name="Cliente",
                customer_tax_id="RUC",
                doc_number="Documento",
                issued_on="Emisión",
                due_on="Vencimiento",
                amount="Monto",
            ),
        ),
    ),
)
