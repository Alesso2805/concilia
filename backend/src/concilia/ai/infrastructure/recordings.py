import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from importlib.resources import files
from typing import Any

from concilia.ai.application.llm import LlmResult
from concilia.ai.application.response import SuggestOutput
from concilia.ai.application.service import CreditKey
from concilia.ai.domain.suggestions import Candidate

RECORDINGS_FILE = "dataset_v1.json"
NO_RECORDING = json.dumps(
    {"suggestions": [], "no_match_reason": "Sin sugerencias en la demo para este abono."}
)
# Not an alias the server ever sends: a recorded document that is no longer a candidate is
# dropped by the same recomputation that drops any invented alias (SPEC).
NOT_A_CANDIDATE = "X"


@dataclass(frozen=True)
class Recordings:
    dataset_version: int
    prompt_version: int
    model: str | None
    outputs: dict[CreditKey, dict[str, Any]] = field(default_factory=dict)


def _key(data: Mapping[str, Any]) -> CreditKey:
    return CreditKey(
        date.fromisoformat(data["booked_on"]),
        data["amount_cents"],
        data["description_norm"],
        data["occurrence"],
    )


def parse_recordings(text: str) -> Recordings:
    data = json.loads(text)
    return Recordings(
        data["dataset_version"],
        data["prompt_version"],
        data["model"],
        {_key(item["credit"]): item["output"] for item in data["recordings"]},
    )


def load_recordings() -> Recordings:
    return parse_recordings(
        files("concilia.ai.recordings").joinpath(RECORDINGS_FILE).read_text(encoding="utf-8")
    )


def dump_recordings(recordings: Recordings) -> str:
    items = sorted(
        recordings.outputs.items(),
        key=lambda item: (
            item[0].booked_on,
            item[0].amount_cents,
            item[0].description_norm,
            item[0].occurrence,
        ),
    )
    return (
        json.dumps(
            {
                "dataset_version": recordings.dataset_version,
                "prompt_version": recordings.prompt_version,
                "model": recordings.model,
                "recordings": [
                    {
                        "credit": {
                            "booked_on": key.booked_on.isoformat(),
                            "amount_cents": key.amount_cents,
                            "description_norm": key.description_norm,
                            "occurrence": key.occurrence,
                        },
                        "output": output,
                    }
                    for key, output in items
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


def to_documents(output: SuggestOutput, candidates: Sequence[Candidate]) -> dict[str, Any]:
    """A model output with each alias replaced by its document number, so it can be replayed
    in any demo; aliases that were not sent are left out."""
    documents = {c.alias: c.receivable.doc_number_norm for c in candidates}
    return {
        "suggestions": [
            {
                "documents": [documents[a] for a in item.candidates if a in documents],
                "applied": (
                    [
                        {"document": documents[pair.alias], "cents": pair.cents}
                        for pair in item.applied
                        if pair.alias in documents
                    ]
                    if item.applied is not None
                    else None
                ),
                "confidence": item.confidence,
                "explanation": item.explanation,
                "difference_reason": item.difference_reason,
            }
            for item in output.suggestions
        ],
        "no_match_reason": output.no_match_reason,
    }


def to_aliases(recorded: Mapping[str, Any], candidates: Sequence[Candidate]) -> str:
    """The recorded output in model form for this demo's candidates."""
    aliases = {c.receivable.doc_number_norm: c.alias for c in candidates}
    return json.dumps(
        {
            "suggestions": [
                {
                    "candidates": [aliases.get(d, NOT_A_CANDIDATE) for d in item["documents"]],
                    "applied": (
                        [
                            {
                                "alias": aliases.get(pair["document"], NOT_A_CANDIDATE),
                                "cents": pair["cents"],
                            }
                            for pair in item["applied"]
                        ]
                        if item["applied"] is not None
                        else None
                    ),
                    "confidence": item["confidence"],
                    "explanation": item["explanation"],
                    "difference_reason": item["difference_reason"],
                }
                for item in recorded["suggestions"]
                if item["documents"]
            ],
            "no_match_reason": recorded["no_match_reason"],
        }
    )


class RecordedReplayer:
    """Deterministic answers for demo organizations from the recordings in the repository."""

    def __init__(self, recordings: Recordings) -> None:
        self._recordings = recordings

    def replay(self, key: CreditKey, candidates: Sequence[Candidate]) -> LlmResult:
        recorded = self._recordings.outputs.get(key)
        model = f"recorded:{self._recordings.model or 'none'}"
        if recorded is None:
            return LlmResult(NO_RECORDING, model, 0, 0)
        return LlmResult(to_aliases(recorded, candidates), model, 0, 0)
