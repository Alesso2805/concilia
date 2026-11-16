from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection


class NoActiveMatches:
    """Stands in for the matching module's query until it exists (CN-12)."""

    def __init__(self, _connection: AsyncConnection) -> None:
        pass

    async def any_active(
        self, movement_ids: Sequence[UUID], receivable_ids: Sequence[UUID]
    ) -> bool:
        return False
