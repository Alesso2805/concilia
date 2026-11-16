from dataclasses import dataclass
from uuid import UUID

from concilia.matching.domain.decisions import DecisionError

MAX_ITEMS = 50


class InvalidManualMatchError(DecisionError):
    code = "invalid_match"


@dataclass(frozen=True)
class ManualApplication:
    receivable_id: UUID
    applied_cents: int


@dataclass(frozen=True)
class ManualMatch:
    credit_ids: tuple[UUID, ...]
    applications: tuple[ManualApplication, ...]

    @property
    def applied_cents(self) -> int:
        return sum(application.applied_cents for application in self.applications)


def check_manual_match(match: ManualMatch) -> None:
    """At least one credit and one receivable, each once, and every applied amount positive.
    Whether the credits are free and the receivables have balance is checked against the data."""
    receivables = [application.receivable_id for application in match.applications]
    if not match.credit_ids or not receivables:
        raise InvalidManualMatchError
    if len(match.credit_ids) + len(receivables) > MAX_ITEMS:
        raise InvalidManualMatchError
    if len(set(match.credit_ids)) != len(match.credit_ids) or len(set(receivables)) != len(
        receivables
    ):
        raise InvalidManualMatchError
    if any(application.applied_cents <= 0 for application in match.applications):
        raise InvalidManualMatchError
