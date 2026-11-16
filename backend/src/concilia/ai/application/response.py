from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from concilia.ai.domain.suggestions import Proposal

Confidence = Literal["low", "medium", "high"]
Reason = Literal["commission", "detraction", "rounding", "overpayment", "other"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AppliedPair(_Strict):
    alias: str = Field(max_length=8)
    cents: int


class SuggestionOutput(_Strict):
    candidates: list[str] = Field(min_length=1, max_length=10)
    applied: list[AppliedPair] | None
    confidence: Confidence
    explanation: str = Field(min_length=1, max_length=1000)
    difference_reason: Reason | None


class SuggestOutput(_Strict):
    suggestions: list[SuggestionOutput] = Field(max_length=3)
    no_match_reason: str | None = Field(max_length=1000)


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


_APPLIED = {
    "type": "object",
    "properties": {"alias": {"type": "string"}, "cents": {"type": "integer"}},
    "required": ["alias", "cents"],
    "additionalProperties": False,
}
_SUGGESTION = {
    "type": "object",
    "properties": {
        "candidates": {"type": "array", "items": {"type": "string"}},
        "applied": _nullable({"type": "array", "items": _APPLIED}),
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "explanation": {"type": "string"},
        "difference_reason": _nullable(
            {
                "type": "string",
                "enum": ["commission", "detraction", "rounding", "overpayment", "other"],
            }
        ),
    },
    "required": ["candidates", "applied", "confidence", "explanation", "difference_reason"],
    "additionalProperties": False,
}
# The provider's strict structured output needs every field required and no free-form keys
# (ADR-0006); limits such as three suggestions are enforced by SuggestOutput instead.
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "suggestions": {"type": "array", "items": _SUGGESTION},
        "no_match_reason": _nullable({"type": "string"}),
    },
    "required": ["suggestions", "no_match_reason"],
    "additionalProperties": False,
}


def parse_output(text: str) -> SuggestOutput | None:
    """The model's output, or None when it is not valid; the provider is never trusted."""
    try:
        return SuggestOutput.model_validate_json(text)
    except ValidationError:
        return None


def proposals(output: SuggestOutput) -> list[Proposal]:
    return [
        Proposal(
            candidates=suggestion.candidates,
            applied=(
                [(pair.alias, pair.cents) for pair in suggestion.applied]
                if suggestion.applied is not None
                else None
            ),
            confidence=suggestion.confidence,
            explanation=suggestion.explanation,
            difference_reason=suggestion.difference_reason,
        )
        for suggestion in output.suggestions
    ]
