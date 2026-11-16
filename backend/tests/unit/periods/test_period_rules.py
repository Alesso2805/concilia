from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from concilia.periods.domain.period import (
    AlreadyClosedError,
    FuturePeriodError,
    InvalidPeriodError,
    NotClosedError,
    PendingMatchesError,
    PeriodAction,
    PeriodError,
    PeriodState,
    ReasonRequiredError,
    RoleRequiredError,
    check_period_action,
)

TODAY = date(2027, 2, 3)
JANUARY = date(2027, 1, 1)
REVIEWER = frozenset({"reviewer"})
OPEN = PeriodState(closed=False, has_pending_matches=False)
CLOSED = PeriodState(closed=True, has_pending_matches=False)


def test_a_reviewer_closes_an_open_month_and_reopens_it_with_a_reason() -> None:
    check_period_action(PeriodAction.CLOSE, JANUARY, TODAY, OPEN, None, REVIEWER)
    check_period_action(PeriodAction.REOPEN, JANUARY, TODAY, CLOSED, "Faltó un abono", REVIEWER)


def test_the_current_month_can_be_closed_but_not_a_later_one() -> None:
    check_period_action(PeriodAction.CLOSE, date(2027, 2, 1), TODAY, OPEN, None, REVIEWER)

    with pytest.raises(FuturePeriodError):
        check_period_action(PeriodAction.CLOSE, date(2027, 3, 1), TODAY, OPEN, None, REVIEWER)


@pytest.mark.parametrize(
    ("action", "period", "state", "reason", "roles", "error"),
    [
        (
            PeriodAction.CLOSE,
            JANUARY,
            OPEN,
            None,
            frozenset({"analyst", "admin"}),
            RoleRequiredError,
        ),
        (PeriodAction.CLOSE, date(2027, 1, 15), OPEN, None, REVIEWER, InvalidPeriodError),
        (PeriodAction.CLOSE, JANUARY, CLOSED, None, REVIEWER, AlreadyClosedError),
        (
            PeriodAction.CLOSE,
            JANUARY,
            PeriodState(closed=False, has_pending_matches=True),
            None,
            REVIEWER,
            PendingMatchesError,
        ),
        (PeriodAction.REOPEN, JANUARY, OPEN, "Motivo", REVIEWER, NotClosedError),
        (PeriodAction.REOPEN, JANUARY, CLOSED, None, REVIEWER, ReasonRequiredError),
    ],
)
def test_refusals(
    action: PeriodAction,
    period: date,
    state: PeriodState,
    reason: str | None,
    roles: frozenset[str],
    error: type[PeriodError],
) -> None:
    with pytest.raises(error):
        check_period_action(action, period, TODAY, state, reason, roles)


@given(
    closed=st.booleans(),
    pending=st.booleans(),
    action=st.sampled_from(PeriodAction),
    reason=st.one_of(st.none(), st.text(min_size=1, max_size=20)),
)
def test_closing_and_reopening_alternate(
    closed: bool, pending: bool, action: PeriodAction, reason: str | None
) -> None:
    state = PeriodState(closed=closed, has_pending_matches=pending)
    try:
        check_period_action(action, JANUARY, TODAY, state, reason, REVIEWER)
    except PeriodError:
        allowed = False
    else:
        allowed = True

    if action is PeriodAction.CLOSE:
        assert allowed == (not closed and not pending)
    else:
        assert allowed == (closed and bool(reason))
