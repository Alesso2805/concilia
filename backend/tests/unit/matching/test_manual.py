from uuid import UUID, uuid7

import pytest

from concilia.matching.domain.manual import (
    MAX_ITEMS,
    InvalidManualMatchError,
    ManualApplication,
    ManualMatch,
    check_manual_match,
)

CREDIT, RECEIVABLE = uuid7(), uuid7()


def _match(credits: list[UUID], applications: list[tuple[UUID, int]]) -> ManualMatch:
    return ManualMatch(
        tuple(credits),
        tuple(ManualApplication(receivable, cents) for receivable, cents in applications),
    )


def test_a_credit_and_a_receivable_with_a_positive_amount_are_enough() -> None:
    match = _match([CREDIT], [(RECEIVABLE, 1)])

    check_manual_match(match)
    assert match.applied_cents == 1


@pytest.mark.parametrize(
    "match",
    [
        _match([], [(RECEIVABLE, 100)]),
        _match([CREDIT], []),
        _match([CREDIT, CREDIT], [(RECEIVABLE, 100)]),
        _match([CREDIT], [(RECEIVABLE, 50), (RECEIVABLE, 50)]),
        _match([CREDIT], [(RECEIVABLE, 0)]),
        _match([CREDIT], [(RECEIVABLE, -5)]),
        _match([uuid7() for _ in range(MAX_ITEMS)], [(RECEIVABLE, 1)]),
    ],
)
def test_malformed_manual_matches_are_refused(match: ManualMatch) -> None:
    with pytest.raises(InvalidManualMatchError):
        check_manual_match(match)
