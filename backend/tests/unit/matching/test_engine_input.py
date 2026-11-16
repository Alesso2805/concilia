from dataclasses import replace
from datetime import date
from uuid import UUID

import pytest

from concilia.matching.domain.model import Credit, EngineInput
from tests.support.engine import PERIOD, credit, receivable


def test_credits_have_a_positive_amount() -> None:
    with pytest.raises(ValueError, match="positive amount"):
        credit(1, 0, "PAGO")


def test_credit_document_references_are_unique() -> None:
    with pytest.raises(ValueError, match="unique"):
        Credit(UUID(int=1), date(2027, 1, 1), 100, "PAGO", ("F001-1", "F001-1"))


def test_open_receivables_have_an_available_balance() -> None:
    with pytest.raises(ValueError, match="available balance"):
        receivable("F001-1", 0)


def test_the_period_starts_on_the_first_day() -> None:
    with pytest.raises(ValueError, match="first day"):
        EngineInput(period=date(2027, 1, 2), credits=(), receivables=())


def test_every_credit_belongs_to_the_period() -> None:
    with pytest.raises(ValueError, match="belongs to the period"):
        EngineInput(
            period=PERIOD, credits=(credit(1, 100, "PAGO", date(2027, 2, 1)),), receivables=()
        )


def test_ids_are_unique() -> None:
    first = receivable("F001-1", 100)
    with pytest.raises(ValueError, match="ids are unique"):
        EngineInput(
            period=PERIOD, credits=(), receivables=(first, replace(first, doc_number_norm="X"))
        )


def test_document_numbers_are_unique() -> None:
    with pytest.raises(ValueError, match="document numbers are unique"):
        EngineInput(
            period=PERIOD,
            credits=(),
            receivables=(
                receivable("F001-1", 100),
                receivable("F001-1", 200, id=UUID(int=99)),
            ),
        )
