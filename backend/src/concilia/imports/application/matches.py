from collections.abc import Sequence
from typing import Protocol
from uuid import UUID


class ActiveMatchesQuery(Protocol):
    """Answered by the matching module; each method returns the given ids that qualify."""

    async def active(
        self, movement_ids: Sequence[UUID], receivable_ids: Sequence[UUID]
    ) -> set[UUID]: ...

    async def pending(
        self, movement_ids: Sequence[UUID], receivable_ids: Sequence[UUID]
    ) -> set[UUID]: ...
