import hashlib
from datetime import datetime
from uuid import UUID, uuid7

from concilia.banking.application.profile_config import (
    ProfileKind,
    ReceivablesConfig,
    StatementConfig,
    parse_config,
)
from concilia.imports.application.parsing import receivable_rows, statement_rows
from concilia.imports.application.service import FileReader, ImportStore, NotFoundError
from concilia.imports.domain.model import FileStatus, ImportFile


async def import_confirmed(
    store: ImportStore,
    reader: FileReader,
    organization_id: UUID,
    *,
    profile_id: UUID,
    filename: str,
    content: bytes,
    actor: UUID,
    now: datetime,
) -> int:
    """Store a file that has to be fully valid as already confirmed; returns its row count."""
    profile = await store.active_profile(profile_id)
    if profile is None:
        raise NotFoundError
    config = parse_config(ProfileKind(profile.kind), profile.config)
    cells = reader.rows(content, config)
    file = ImportFile(
        uuid7(),
        profile.kind.value,
        profile.bank_account_id,
        profile.id,
        {"name": profile.name, "config": dict(profile.config)},
        filename,
        hashlib.sha256(content).hexdigest(),
        len(content),
        FileStatus.CONFIRMED,
        None,
        None,
        actor,
        now,
    )
    await store.insert_file(organization_id, file, content)
    if isinstance(config, StatementConfig) and profile.bank_account_id is not None:
        rows = statement_rows(cells, config, profile.bank_account_id)
        await store.insert_movements(organization_id, file, rows, now)
    elif isinstance(config, ReceivablesConfig):
        rows = receivable_rows(cells, config)
        await store.insert_receivables(organization_id, file.id, rows, now)
    else:
        raise NotFoundError
    await store.update_file(file.id, row_count=len(rows), confirmed_at=now)
    return len(rows)
