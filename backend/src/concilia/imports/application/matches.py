from collections.abc import Sequence
from typing import Protocol
from uuid import UUID


class ActiveMatchesQuery(Protocol):
    async def any_active(
        self, movement_ids: Sequence[UUID], receivable_ids: Sequence[UUID]
    ) -> bool: ...
