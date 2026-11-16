from collections.abc import Sequence
from datetime import datetime
from uuid import UUID, uuid7

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def insert_match(
    owner_engine: AsyncEngine,
    *,
    organization_id: UUID,
    bank_account_id: UUID,
    created_by: UUID,
    credits: Sequence[UUID],
    applications: Sequence[tuple[UUID, int]],
    decisions: Sequence[tuple[str, UUID]] = (),
    at: datetime,
) -> UUID:
    match = uuid7()
    params = {"org": organization_id, "match": match, "now": at}
    async with owner_engine.begin() as connection:
        await connection.execute(
            text(
                """INSERT INTO matches (id, organization_id, bank_account_id, source, created_by,
                                        created_at)
                   VALUES (:match, :org, :account, 'manual', :user, :now)"""
            ),
            {**params, "account": bank_account_id, "user": created_by},
        )
        for credit in credits:
            await connection.execute(
                text(
                    """INSERT INTO match_items (id, organization_id, match_id, bank_movement_id)
                       VALUES (:id, :org, :match, :credit)"""
                ),
                {**params, "id": uuid7(), "credit": credit},
            )
        for receivable, applied in applications:
            await connection.execute(
                text(
                    """INSERT INTO match_items (id, organization_id, match_id, receivable_id,
                                                applied_cents)
                       VALUES (:id, :org, :match, :receivable, :applied)"""
                ),
                {**params, "id": uuid7(), "receivable": receivable, "applied": applied},
            )
        for action, user in decisions:
            await connection.execute(
                text(
                    """INSERT INTO match_decisions (id, organization_id, match_id, action, reason,
                                                    decided_by, decided_at)
                       VALUES (:id, :org, :match, :action, 'Motivo', :user, :now)"""
                ),
                {**params, "id": uuid7(), "action": action, "user": user},
            )
    return match
