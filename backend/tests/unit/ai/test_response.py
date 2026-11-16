import hashlib
import json
from datetime import date
from typing import Any
from uuid import UUID

import pytest

from concilia.ai.application.prompts import PROMPT_FILES, system_prompt, user_input
from concilia.ai.application.response import (
    RESPONSE_SCHEMA,
    SuggestionOutput,
    SuggestOutput,
    parse_output,
    proposals,
)
from concilia.ai.domain.suggestions import Candidate, CreditFacts, OpenReceivable
from concilia.ai.infrastructure.fake_llm import NO_SUGGESTIONS

# Editing a prompt without bumping its version fails here (ADR-0006); a new version also needs
# new demo recordings.
PROMPT_SHA256 = {1: "6acbbfe2ae4fcf3b61aea96828d729e9c41323adbe074a388e08ced0f9df62f4"}

VALID: dict[str, Any] = {
    "suggestions": [
        {
            "candidates": ["C1", "C2"],
            "applied": [{"alias": "C1", "cents": 100}, {"alias": "C2", "cents": 50}],
            "confidence": "medium",
            "explanation": "La descripción menciona F001-1.",
            "difference_reason": None,
        }
    ],
    "no_match_reason": None,
}


def test_each_prompt_version_is_pinned_to_its_text() -> None:
    assert set(PROMPT_SHA256) == set(PROMPT_FILES)
    for version, digest in PROMPT_SHA256.items():
        assert hashlib.sha256(system_prompt(version).encode()).hexdigest() == digest


def test_only_the_allowed_fields_leave_the_organization() -> None:
    credit = CreditFacts(UUID(int=1), date(2027, 1, 5), 118_000, "PAGO F001-1", "PAGO F001 1")
    receivable = OpenReceivable(
        id=UUID(int=2),
        doc_number="F001-1",
        doc_number_norm="F001-1",
        customer_name="Comercial Andina SAC",
        customer_name_norm="COMERCIAL ANDINA SAC",
        customer_tax_id="20512345678",
        issued_on=date(2027, 1, 1),
        due_on=date(2027, 1, 31),
        available_cents=118_000,
    )

    sent = json.loads(user_input(credit, [Candidate("C1", receivable)]))

    assert set(sent) == {"abono", "candidatos"}
    assert set(sent["abono"]) == {"fecha", "monto_centimos", "descripcion"}
    assert sent["candidatos"] == [
        {
            "alias": "C1",
            "documento": "F001-1",
            "cliente": "Comercial Andina SAC",
            "saldo_disponible_centimos": 118_000,
            "emision": "2027-01-01",
            "vencimiento": "2027-01-31",
        }
    ]
    assert str(receivable.id) not in json.dumps(sent)
    assert "20512345678" not in json.dumps(sent)


def test_a_valid_output_becomes_proposals() -> None:
    output = parse_output(json.dumps(VALID))

    assert output is not None
    [proposal] = proposals(output)
    assert proposal.candidates == ["C1", "C2"]
    assert proposal.applied == [("C1", 100), ("C2", 50)]
    assert parse_output(NO_SUGGESTIONS) is not None


@pytest.mark.parametrize(
    "broken",
    [
        "not json",
        json.dumps({**VALID, "extra": 1}),
        json.dumps({"suggestions": []}),
        json.dumps({**VALID, "suggestions": VALID["suggestions"] * 4}),
        json.dumps(
            {**VALID, "suggestions": [{**VALID["suggestions"][0], "confidence": "certain"}]}
        ),
        json.dumps({**VALID, "suggestions": [{**VALID["suggestions"][0], "candidates": []}]}),
        json.dumps(
            {
                **VALID,
                "suggestions": [
                    {**VALID["suggestions"][0], "applied": [{"alias": "C1", "cents": "100"}]}
                ],
            }
        ),
    ],
    ids=["text", "extra key", "missing key", "four", "confidence", "no candidates", "string"],
)
def test_invalid_outputs_are_refused(broken: str) -> None:
    assert parse_output(broken) is None


def _objects(schema: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            found.append(schema)
        for value in schema.values():
            found.extend(_objects(value))
    elif isinstance(schema, list):
        for value in schema:
            found.extend(_objects(value))
    return found


def test_the_schema_is_strict_and_matches_the_validating_models() -> None:
    objects = _objects(RESPONSE_SCHEMA)

    assert all(o["additionalProperties"] is False for o in objects)
    assert all(set(o["required"]) == set(o["properties"]) for o in objects)
    top, suggestion = RESPONSE_SCHEMA, RESPONSE_SCHEMA["properties"]["suggestions"]["items"]
    assert set(top["properties"]) == set(SuggestOutput.model_fields)
    assert set(suggestion["properties"]) == set(SuggestionOutput.model_fields)
