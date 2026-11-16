from datetime import date
from typing import Protocol
from uuid import UUID


class PendingMatchesQuery(Protocol):
    """Answered by the matching module."""

    async def any_pending(self, bank_account_id: UUID, period: date) -> bool:
        """Whether a proposed or confirmed match has a credit of this account and month."""
        ...
