from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from concilia.matching.domain.inbox import MatchStatus
from concilia.matching.domain.model import DifferenceReason

MAX_TEXT = 500


class Action(StrEnum):
    CONFIRM = "confirm"
    DISCARD = "discard"
    APPROVE = "approve"
    REJECT = "reject"
    REVERT = "revert"


ANALYST_ACTIONS = frozenset({Action.CONFIRM, Action.DISCARD})
REVIEWER_ACTIONS = frozenset({Action.APPROVE, Action.REJECT, Action.REVERT})
NEEDS_REASON = frozenset({Action.REJECT, Action.REVERT})
TRANSITIONS: dict[MatchStatus, frozenset[Action]] = {
    MatchStatus.PROPOSED: frozenset({Action.CONFIRM, Action.DISCARD}),
    MatchStatus.CONFIRMED: frozenset({Action.APPROVE, Action.REJECT}),
    MatchStatus.APPROVED: frozenset({Action.REVERT}),
}
RESULT: dict[Action, MatchStatus] = {
    Action.CONFIRM: MatchStatus.CONFIRMED,
    Action.DISCARD: MatchStatus.DISCARDED,
    Action.APPROVE: MatchStatus.APPROVED,
    Action.REJECT: MatchStatus.REJECTED,
    Action.REVERT: MatchStatus.REVERTED,
}


class DecisionError(Exception):
    code = "invalid_decision"


class RoleRequiredError(DecisionError):
    code = "role_required"


class WrongStateError(DecisionError):
    code = "wrong_state"


class FourEyesError(DecisionError):
    code = "four_eyes"


class ClosedPeriodError(DecisionError):
    code = "closed_period"


class ReasonRequiredError(DecisionError):
    code = "reason_required"


class DifferenceReasonError(DecisionError):
    code = "difference_reason"


@dataclass(frozen=True)
class MatchState:
    status: MatchStatus
    created_by: UUID | None
    confirmed_by: UUID | None
    difference_cents: int
    in_closed_period: bool


@dataclass(frozen=True)
class DecisionRequest:
    action: Action
    reason: str | None = None
    difference_reason: DifferenceReason | None = None
    difference_note: str | None = None


def _check_difference(state: MatchState, request: DecisionRequest) -> None:
    reason, note = request.difference_reason, request.difference_note
    if request.action != Action.CONFIRM:
        if reason is not None or note is not None:
            raise DifferenceReasonError
        return
    if (state.difference_cents != 0) != (reason is not None):
        raise DifferenceReasonError
    if reason == DifferenceReason.OVERPAYMENT and state.difference_cents <= 0:
        raise DifferenceReasonError
    if (reason == DifferenceReason.OTHER) != bool(note and note.strip()):
        raise DifferenceReasonError


def check_decision(
    state: MatchState, request: DecisionRequest, actor: UUID, roles: frozenset[str]
) -> None:
    """The rules of the state table: who may take which action, and with what."""
    action = request.action
    needed = "analyst" if action in ANALYST_ACTIONS else "reviewer"
    if needed not in roles:
        raise RoleRequiredError
    if action not in TRANSITIONS.get(state.status, frozenset()):
        raise WrongStateError
    if state.in_closed_period:
        raise ClosedPeriodError
    if action in REVIEWER_ACTIONS and actor in {state.created_by, state.confirmed_by}:
        raise FourEyesError
    reason = (request.reason or "").strip()
    if action in NEEDS_REASON and not reason:
        raise ReasonRequiredError
    if len(reason) > MAX_TEXT or len((request.difference_note or "").strip()) > MAX_TEXT:
        raise ReasonRequiredError
    _check_difference(state, request)
