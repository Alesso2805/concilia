from uuid import uuid7

import pytest

from concilia.audit.application.log import (
    AuditFilters,
    AuditLogService,
    AuditorRequiredError,
)
from concilia.shared.kernel.principal import Principal


class NoTransactions:
    def organization(self, organization_id: object) -> object:
        raise AssertionError("the log must not be read")


@pytest.mark.anyio
@pytest.mark.parametrize(
    "principal",
    [
        Principal(uuid7(), uuid7(), None, frozenset({"admin"})),
        Principal(uuid7(), uuid7(), uuid7(), frozenset()),
    ],
)
async def test_the_log_needs_an_organization_and_a_role(principal: Principal) -> None:
    service = AuditLogService(NoTransactions())  # type: ignore[arg-type]

    with pytest.raises(AuditorRequiredError):
        await service.page(principal, AuditFilters(), after=None, before=None, limit=10)
    with pytest.raises(AuditorRequiredError):
        await service.actors(principal)
