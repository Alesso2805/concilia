from dataclasses import dataclass
from datetime import date
from enum import StrEnum

REVIEWER = "reviewer"
MAX_REASON = 500


def period_of(day: date) -> date:
    return day.replace(day=1)


class PeriodAction(StrEnum):
    CLOSE = "close"
    REOPEN = "reopen"


class PeriodError(Exception):
    code = "invalid_period_action"


class RoleRequiredError(PeriodError):
    code = "role_required"


class InvalidPeriodError(PeriodError):
    code = "invalid_period"


class FuturePeriodError(PeriodError):
    code = "future_period"


class AlreadyClosedError(PeriodError):
    code = "already_closed"


class NotClosedError(PeriodError):
    code = "not_closed"


class PendingMatchesError(PeriodError):
    code = "pending_matches"


class ReasonRequiredError(PeriodError):
    code = "reason_required"


@dataclass(frozen=True)
class PeriodState:
    closed: bool
    has_pending_matches: bool


def check_period_action(
    action: PeriodAction,
    period: date,
    today: date,
    state: PeriodState,
    reason: str | None,
    roles: frozenset[str],
) -> None:
    """A reviewer closes an open month with nothing proposed or confirmed, and reopens a closed
    one with a reason; months after the current one stay open."""
    if REVIEWER not in roles:
        raise RoleRequiredError
    if period.day != 1:
        raise InvalidPeriodError
    if period > period_of(today):
        raise FuturePeriodError
    if action is PeriodAction.CLOSE:
        if state.closed:
            raise AlreadyClosedError
        if state.has_pending_matches:
            raise PendingMatchesError
        return
    if not state.closed:
        raise NotClosedError
    if not reason:
        raise ReasonRequiredError
