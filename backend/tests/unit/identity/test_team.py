from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

import pytest
from hypothesis import given
from hypothesis import strategies as st

from concilia.identity.domain.model import Role
from concilia.identity.domain.team import (
    InvalidEmailError,
    Invitation,
    LastAdminError,
    NoRolesError,
    check_email,
    ensure_an_admin_remains,
    parse_roles,
)

NOW = datetime(2026, 11, 23, 14, 0, tzinfo=UTC)
role_sets = st.frozensets(st.sampled_from(list(Role)))


def test_roles_are_required_and_known() -> None:
    assert parse_roles(["admin", "analyst", "admin"]) == {Role.ADMIN, Role.ANALYST}
    with pytest.raises(NoRolesError):
        parse_roles([])
    with pytest.raises(ValueError, match="owner"):
        parse_roles(["owner"])


@pytest.mark.parametrize("email", ["ana", "ana@", "@example.test", "ana @example.test", "a@b"])
def test_malformed_emails_are_rejected(email: str) -> None:
    with pytest.raises(InvalidEmailError):
        check_email(email)


def test_a_plain_email_is_accepted() -> None:
    assert check_email("ana.torres+pagos@example.test") == "ana.torres+pagos@example.test"


@pytest.mark.parametrize(
    ("accepted", "revoked", "expires_in", "pending"),
    [
        (False, False, timedelta(days=1), True),
        (True, False, timedelta(days=1), False),
        (False, True, timedelta(days=1), False),
        (False, False, timedelta(0), False),
    ],
)
def test_pending_invitations(
    accepted: bool, revoked: bool, expires_in: timedelta, pending: bool
) -> None:
    invitation = Invitation(
        uuid7(),
        uuid7(),
        "ana@example.test",
        frozenset({Role.ANALYST}),
        uuid7(),
        NOW - timedelta(days=1),
        NOW + expires_in,
        NOW if accepted else None,
        NOW if revoked else None,
    )

    assert invitation.is_pending(NOW) is pending


@given(st.dictionaries(st.uuids(), role_sets, min_size=1, max_size=5), role_sets)
def test_a_change_is_refused_exactly_when_no_admin_would_remain(
    members: dict[UUID, frozenset[Role]], new_roles: frozenset[Role]
) -> None:
    target = next(iter(members))
    after = {**members, target: new_roles}
    keeps_admin = any(Role.ADMIN in roles for roles in after.values())

    if keeps_admin:
        ensure_an_admin_remains(members, target, new_roles)
    else:
        with pytest.raises(LastAdminError):
            ensure_an_admin_remains(members, target, new_roles)
