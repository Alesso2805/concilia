from uuid import UUID, uuid7

import pytest
from hypothesis import given
from hypothesis import strategies as st

from concilia.matching.domain.decisions import (
    TRANSITIONS,
    Action,
    ClosedPeriodError,
    DecisionError,
    DecisionRequest,
    DifferenceReasonError,
    FourEyesError,
    MatchState,
    ReasonRequiredError,
    RoleRequiredError,
    WrongStateError,
    check_decision,
)
from concilia.matching.domain.inbox import MatchStatus
from concilia.matching.domain.model import DifferenceReason

ANALYST, REVIEWER, OTHER_REVIEWER = uuid7(), uuid7(), uuid7()
BOTH = frozenset({"analyst", "reviewer"})


def _state(
    status: MatchStatus = MatchStatus.PROPOSED,
    created_by: UUID | None = None,
    confirmed_by: UUID | None = None,
    difference: int = 0,
    closed: bool = False,
) -> MatchState:
    return MatchState(status, created_by, confirmed_by, difference, closed)


def _decide(
    state: MatchState,
    action: Action,
    actor: UUID = REVIEWER,
    roles: frozenset[str] = BOTH,
    **fields: object,
) -> None:
    check_decision(state, DecisionRequest(action, **fields), actor, roles)  # type: ignore[arg-type]


@pytest.mark.parametrize("status", list(MatchStatus))
@pytest.mark.parametrize("action", list(Action))
def test_only_the_state_table_transitions_are_allowed(status: MatchStatus, action: Action) -> None:
    state = _state(status, confirmed_by=ANALYST)
    allowed = action in TRANSITIONS.get(status, frozenset())

    if allowed:
        _decide(state, action, OTHER_REVIEWER, reason="Motivo")
    else:
        with pytest.raises(WrongStateError):
            _decide(state, action, OTHER_REVIEWER, reason="Motivo")


@pytest.mark.parametrize(
    ("action", "roles"),
    [
        (Action.CONFIRM, frozenset({"reviewer"})),
        (Action.DISCARD, frozenset({"admin"})),
        (Action.APPROVE, frozenset({"analyst"})),
        (Action.REJECT, frozenset({"admin", "analyst"})),
    ],
)
def test_each_action_needs_its_role(action: Action, roles: frozenset[str]) -> None:
    status = (
        MatchStatus.PROPOSED
        if action in {Action.CONFIRM, Action.DISCARD}
        else (MatchStatus.CONFIRMED)
    )
    with pytest.raises(RoleRequiredError):
        _decide(_state(status), action, roles=roles, reason="Motivo")


@pytest.mark.parametrize("action", [Action.APPROVE, Action.REJECT])
def test_who_created_or_confirmed_a_match_never_approves_or_rejects_it(action: Action) -> None:
    created = _state(MatchStatus.CONFIRMED, created_by=REVIEWER, confirmed_by=ANALYST)
    confirmed = _state(MatchStatus.CONFIRMED, confirmed_by=REVIEWER)

    for state in (created, confirmed):
        with pytest.raises(FourEyesError):
            _decide(state, action, REVIEWER, reason="Motivo")
    _decide(confirmed, action, OTHER_REVIEWER, reason="Motivo")


def test_nor_reverts_it() -> None:
    with pytest.raises(FourEyesError):
        _decide(_state(MatchStatus.APPROVED, confirmed_by=REVIEWER), Action.REVERT, reason="x")


def test_an_engine_proposal_can_be_confirmed_by_anyone_with_the_role() -> None:
    _decide(_state(MatchStatus.PROPOSED), Action.CONFIRM, ANALYST)


def test_a_match_in_a_closed_period_takes_no_action() -> None:
    with pytest.raises(ClosedPeriodError):
        _decide(_state(closed=True), Action.DISCARD, ANALYST)


@pytest.mark.parametrize("reason", [None, "", "   ", "x" * 501])
@pytest.mark.parametrize("action", [Action.REJECT, Action.REVERT])
def test_reject_and_revert_need_a_short_reason(action: Action, reason: str | None) -> None:
    status = MatchStatus.CONFIRMED if action == Action.REJECT else MatchStatus.APPROVED
    with pytest.raises(ReasonRequiredError):
        _decide(_state(status, confirmed_by=ANALYST), action, reason=reason)


@given(
    difference=st.integers(-1_000_000, 1_000_000),
    reason=st.one_of(st.none(), st.sampled_from(DifferenceReason)),
    note=st.one_of(st.none(), st.just(""), st.just("Pago de otra factura")),
)
def test_a_confirmed_difference_has_a_reason_that_fits_it(
    difference: int, reason: DifferenceReason | None, note: str | None
) -> None:
    acceptable = (
        (difference != 0) == (reason is not None)
        and (reason != DifferenceReason.OVERPAYMENT or difference > 0)
        and (reason == DifferenceReason.OTHER) == bool(note)
    )
    state = _state(difference=difference)

    if acceptable:
        _decide(state, Action.CONFIRM, ANALYST, difference_reason=reason, difference_note=note)
    else:
        with pytest.raises(DifferenceReasonError):
            _decide(state, Action.CONFIRM, ANALYST, difference_reason=reason, difference_note=note)


def test_only_a_confirmation_carries_a_difference_reason() -> None:
    with pytest.raises(DifferenceReasonError):
        _decide(_state(), Action.DISCARD, ANALYST, difference_reason=DifferenceReason.OTHER)


def test_every_decision_error_has_its_own_code() -> None:
    errors = DecisionError.__subclasses__()
    codes = [error.code for error in errors]

    assert len(set(codes)) == len(codes)
    assert DecisionError.code not in codes
    assert {
        "role_required",
        "wrong_state",
        "four_eyes",
        "closed_period",
        "reason_required",
        "difference_reason",
    } <= set(codes)
