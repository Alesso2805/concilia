"""`make record-ai`: records the provider's answers for the demo dataset (SPEC, "Respuestas
grabadas de la demo"). It loads a fresh demo, turns it into a regular organization so that no
demo ever reaches the provider, asks the provider about every credit of the demo's second
month with the owner's key, and prints the recordings as JSON."""

import asyncio
import os
import secrets
import sys
from datetime import timedelta
from uuid import UUID

import httpx
from pydantic import SecretStr
from sqlalchemy import text

from concilia.ai.application.prompts import PROMPT_VERSION, system_prompt, user_input
from concilia.ai.application.response import RESPONSE_SCHEMA, parse_output
from concilia.ai.domain.suggestions import choose_candidates
from concilia.ai.infrastructure.openai_llm import OpenAiLlmClient
from concilia.ai.infrastructure.recordings import Recordings, dump_recordings, to_documents
from concilia.ai.infrastructure.sql import SqlSuggestionStore
from concilia.api import create_app
from concilia.audit.infrastructure.sql import SqlAuditRecorder
from concilia.demo.domain.dataset import DATASET_VERSION, build_dataset
from concilia.shared.infrastructure.db import create_engine, organization_transaction
from concilia.shared.infrastructure.settings import ApiSettings

ORIGIN = "https://record-ai.invalid"


async def _load_demo(database_url: str) -> UUID:
    settings = ApiSettings(
        database_url=database_url,
        public_origin=ORIGIN,
        csrf_secret=SecretStr(secrets.token_hex()),
        rate_limit_secret=SecretStr(secrets.token_hex()),
        demo_max_per_ip_per_day=1_000,
        demo_max_per_day=1_000,
    )
    app = create_app(settings)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url=ORIGIN, headers={"Origin": ORIGIN}
        ) as client:
            created = await client.post("/api/public/demo")
            created.raise_for_status()
            return UUID(created.json()["organization_id"])
    finally:
        await app.state.engine.dispose()


async def record(database_url: str, api_key: str, model: str) -> Recordings:
    organization_id = await _load_demo(database_url)
    engine = create_engine(database_url)
    provider = OpenAiLlmClient(api_key, model)
    month = build_dataset().months[1].period
    outputs = {}
    answered_by = model
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """UPDATE organizations SET is_demo = false, demo_expires_at = NULL
                       WHERE id = :id"""
                ),
                {"id": organization_id},
            )
        async with organization_transaction(engine, organization_id) as connection:
            store = SqlSuggestionStore(connection, SqlAuditRecorder(connection))
            credit_ids = list(
                await connection.scalars(
                    text(
                        """SELECT id FROM bank_movements
                           WHERE amount_cents > 0 AND booked_on >= :start AND booked_on < :end
                           ORDER BY booked_on, id"""
                    ),
                    {"start": month, "end": month + timedelta(days=32)},
                )
            )
            receivables = await store.open_receivables()
            for credit_id in credit_ids:
                credit = await store.free_credit(credit_id)
                if credit is None or credit.booked_on.month != month.month:
                    continue
                candidates = choose_candidates(credit, receivables)
                if not candidates:
                    continue
                result = await provider.complete(
                    system=system_prompt(PROMPT_VERSION),
                    user=user_input(credit, candidates),
                    schema=RESPONSE_SCHEMA,
                )
                output = parse_output(result.output)
                if output is not None:
                    outputs[await store.credit_key(credit_id)] = to_documents(output, candidates)
                    answered_by = result.model
                sys.stderr.write(f"{len(outputs)} recorded\n")
    finally:
        await engine.dispose()
    return Recordings(DATASET_VERSION, PROMPT_VERSION, answered_by, outputs)


def main() -> None:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is required to record")
    recordings = asyncio.run(
        record(
            os.environ["CONCILIA_MIGRATIONS_DATABASE_URL"],
            api_key,
            os.environ.get("CONCILIA_AI_MODEL", "gpt-6-luna"),
        )
    )
    sys.stdout.write(dump_recordings(recordings))


if __name__ == "__main__":
    main()
