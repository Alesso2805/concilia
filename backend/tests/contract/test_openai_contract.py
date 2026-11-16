"""Optional contract test against the real provider (ADR-0006). It never runs in the default
CI: run it by hand with `CONCILIA_PROVIDER_CONTRACT=1` and `OPENAI_API_KEY` set. One call costs
a fraction of a cent and sends only fictitious data."""

import os
from datetime import date
from uuid import UUID

import pytest

from concilia.ai.application.prompts import system_prompt, user_input
from concilia.ai.application.response import RESPONSE_SCHEMA, parse_output
from concilia.ai.domain.suggestions import Candidate, CreditFacts, OpenReceivable
from concilia.ai.infrastructure.openai_llm import OpenAiLlmClient

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.environ.get("CONCILIA_PROVIDER_CONTRACT") or not os.environ.get("OPENAI_API_KEY"),
        reason="contract test against the real provider runs only by hand",
    ),
]


async def test_the_provider_answers_with_output_that_validates() -> None:
    credit = CreditFacts(
        UUID(int=1), date(2027, 1, 5), 118_000, "PAGO FACT F001-123 ANDINA", "PAGO FACT F001 123"
    )
    receivable = OpenReceivable(
        id=UUID(int=2),
        doc_number="F001-123",
        doc_number_norm="F001-123",
        customer_name="Comercial Andina SAC (ficticio)",
        customer_name_norm="COMERCIAL ANDINA SAC FICTICIO",
        customer_tax_id=None,
        issued_on=date(2027, 1, 2),
        due_on=date(2027, 1, 31),
        available_cents=118_000,
    )
    client = OpenAiLlmClient(
        os.environ["OPENAI_API_KEY"], os.environ.get("CONCILIA_AI_MODEL", "gpt-6-luna")
    )

    result = await client.complete(
        system=system_prompt(),
        user=user_input(credit, [Candidate("C1", receivable)]),
        schema=RESPONSE_SCHEMA,
    )

    assert parse_output(result.output) is not None
    assert result.input_tokens > 0
