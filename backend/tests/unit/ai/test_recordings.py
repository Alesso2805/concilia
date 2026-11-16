import json
from datetime import date
from uuid import UUID

from concilia.ai.application.prompts import PROMPT_VERSION
from concilia.ai.application.response import parse_output, proposals
from concilia.ai.application.service import CreditKey
from concilia.ai.domain.suggestions import Candidate, OpenReceivable, recompute_all
from concilia.ai.infrastructure.recordings import (
    NO_RECORDING,
    RecordedReplayer,
    Recordings,
    dump_recordings,
    load_recordings,
    parse_recordings,
    to_aliases,
    to_documents,
)
from concilia.demo.domain.dataset import DATASET_VERSION

KEY = CreditKey(date(2026, 11, 4), 50_000, "TRANSF GLORIA", 0)


def _candidate(alias: str, n: int, available: int = 50_000) -> Candidate:
    return Candidate(
        alias,
        OpenReceivable(
            id=UUID(int=n),
            doc_number=f"F001-{n}",
            doc_number_norm=f"F001-{n}",
            customer_name="Gloria SA",
            customer_name_norm="GLORIA SA",
            customer_tax_id=None,
            issued_on=date(2026, 10, 1),
            due_on=date(2026, 11, 15),
            available_cents=available,
        ),
    )


OUTPUT = json.dumps(
    {
        "suggestions": [
            {
                "candidates": ["C2", "C1"],
                "applied": [{"alias": "C2", "cents": 30_000}, {"alias": "C1", "cents": 20_000}],
                "confidence": "medium",
                "explanation": "Dos facturas de Gloria suman el abono.",
                "difference_reason": None,
            }
        ],
        "no_match_reason": None,
    }
)


def test_the_shipped_recordings_match_the_current_prompt_and_dataset() -> None:
    recordings = load_recordings()

    assert (recordings.prompt_version, recordings.dataset_version) == (
        PROMPT_VERSION,
        DATASET_VERSION,
    ), "record the demo again with `make record-ai` after changing the prompt or dataset"


def test_a_recording_replays_by_document_in_another_demo_with_other_aliases() -> None:
    recorded_in = [_candidate("C1", 1), _candidate("C2", 2)]
    output = parse_output(OUTPUT)
    assert output is not None
    recorded = to_documents(output, recorded_in)
    replayed_in = [_candidate("C1", 2), _candidate("C2", 7), _candidate("C3", 1)]

    replayed = parse_output(to_aliases(recorded, replayed_in))

    assert replayed is not None
    [suggestion] = replayed.suggestions
    assert suggestion.candidates == ["C1", "C3"]
    assert [(p.alias, p.cents) for p in suggestion.applied or []] == [
        ("C1", 30_000),
        ("C3", 20_000),
    ]


def test_a_recorded_document_that_is_no_longer_a_candidate_is_dropped() -> None:
    output = parse_output(OUTPUT)
    assert output is not None
    recorded = to_documents(output, [_candidate("C1", 1), _candidate("C2", 2)])
    candidates = [_candidate("C1", 2, available=40_000)]

    replayed = parse_output(to_aliases(recorded, candidates))
    assert replayed is not None
    [kept] = recompute_all(50_000, proposals(replayed), candidates)

    assert [(a.alias, a.applied_cents) for a in kept.applied] == [("C1", 40_000)]
    assert kept.recomputed


def test_recordings_survive_a_round_trip_and_a_missing_one_answers_no_suggestions() -> None:
    output = parse_output(OUTPUT)
    assert output is not None
    recordings = Recordings(
        1, 1, "gpt-6-luna", {KEY: to_documents(output, [_candidate("C1", 1), _candidate("C2", 2)])}
    )

    again = parse_recordings(dump_recordings(recordings))
    replayer = RecordedReplayer(again)
    other = CreditKey(KEY.booked_on, KEY.amount_cents, KEY.description_norm, 1)

    assert again == recordings
    assert replayer.replay(other, [_candidate("C1", 1)]).output == NO_RECORDING
    assert replayer.replay(KEY, [_candidate("C1", 1)]).model == "recorded:gpt-6-luna"
