from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID


@dataclass(frozen=True)
class EngineRun:
    id: UUID
    bank_account_id: UUID
    period: date
    job_id: UUID | None
    rules_version: int
    proposals_count: int | None
    started_at: datetime
    finished_at: datetime | None
