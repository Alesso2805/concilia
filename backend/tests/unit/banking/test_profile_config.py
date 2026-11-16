from typing import Any

import pytest
from pydantic import ValidationError

from concilia.banking.application.profile_config import ProfileKind, parse_config
from concilia.banking.application.templates import TEMPLATES

STATEMENT: dict[str, Any] = {
    "format": "csv",
    "delimiter": ";",
    "date_format": "DD/MM/YYYY",
    "decimal_separator": ",",
    "thousands_separator": ".",
    "columns": {"date": "Fecha", "description": "Detalle", "amount": "Importe"},
}


def _statement(**changes: Any) -> dict[str, Any]:
    return {**STATEMENT, **changes}


def test_a_signed_amount_statement_is_valid_and_versioned() -> None:
    config = parse_config(ProfileKind.BANK_STATEMENT, STATEMENT)

    assert config.version == 1
    assert config.model_dump(mode="json")["columns"]["amount"] == "Importe"


def test_split_debit_and_credit_columns_are_valid() -> None:
    columns = {"date": "Fecha", "description": "Detalle", "debit": "Cargo", "credit": "Abono"}

    config = parse_config(ProfileKind.BANK_STATEMENT, _statement(columns=columns))

    assert config.model_dump()["columns"]["credit"] == "Abono"


@pytest.mark.parametrize(
    "changes",
    [
        {"columns": {"date": "Fecha", "description": "Detalle"}},
        {"columns": {"date": "F", "description": "D", "amount": "M", "debit": "C", "credit": "A"}},
        {"columns": {"date": "F", "description": "D", "debit": "C"}},
        {"columns": {"date": "Fecha", "description": "fecha", "amount": "M"}},
        {"thousands_separator": ","},
        {"decimal_separator": ".", "thousands_separator": "."},
        {"sheet": "Hoja1"},
        {"skip_rows": 51},
        {"date_format": "MM/DD/YYYY"},
        {"version": 2},
        {"formula": "=1+1"},
    ],
)
def test_inconsistent_statement_configs_are_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        parse_config(ProfileKind.BANK_STATEMENT, _statement(**changes))


def test_a_receivables_config_needs_its_own_columns() -> None:
    with pytest.raises(ValidationError):
        parse_config(ProfileKind.RECEIVABLES, STATEMENT)


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda template: template.key)
def test_every_template_round_trips_through_validation(template: Any) -> None:
    raw = template.config.model_dump(mode="json")

    assert parse_config(template.kind, raw) == template.config
    assert (template.bank is None) == (template.kind == ProfileKind.RECEIVABLES)
