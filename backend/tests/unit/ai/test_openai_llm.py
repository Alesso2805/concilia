from types import SimpleNamespace
from typing import Any, cast

import httpx2 as httpx
import pytest
from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
)
from pydantic import SecretStr

from concilia.ai.application.llm import LlmError
from concilia.ai.application.response import RESPONSE_SCHEMA
from concilia.ai.infrastructure.clients import llm_clients
from concilia.ai.infrastructure.fake_llm import FakeLlmClient
from concilia.ai.infrastructure.openai_llm import OpenAiLlmClient
from concilia.shared.infrastructure.settings import AiSettings

pytestmark = pytest.mark.anyio

REQUEST = httpx.Request("POST", "https://api.openai.com/v1/responses")
OUTPUT = '{"suggestions": [], "no_match_reason": "Ninguno coincide."}'


class Responses:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome
        self.params: dict[str, Any] = {}

    async def create(self, **params: Any) -> object:
        self.params = params
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _client(outcome: object) -> tuple[OpenAiLlmClient, Responses]:
    responses = Responses(outcome)
    stub = cast(AsyncOpenAI, SimpleNamespace(responses=responses))
    return OpenAiLlmClient("sk-test", "gpt-6-luna", client=stub), responses


async def test_requests_strict_structured_output_and_stores_nothing_at_the_provider() -> None:
    answer = SimpleNamespace(
        output_text=OUTPUT,
        model="gpt-6-luna-2026-10-01",
        usage=SimpleNamespace(input_tokens=1_200, output_tokens=300),
    )
    client, responses = _client(answer)

    result = await client.complete(
        system="Instrucciones", user='{"abono": {}}', schema=RESPONSE_SCHEMA
    )

    assert (result.output, result.model, result.input_tokens, result.output_tokens) == (
        OUTPUT,
        "gpt-6-luna-2026-10-01",
        1_200,
        300,
    )
    params = responses.params
    assert (params["model"], params["instructions"], params["input"]) == (
        "gpt-6-luna",
        "Instrucciones",
        '{"abono": {}}',
    )
    assert params["text"]["format"]["strict"] is True
    assert params["text"]["format"]["schema"] == RESPONSE_SCHEMA
    assert params["store"] is False
    assert params["reasoning"] == {"effort": "low"}


@pytest.mark.parametrize(
    ("failure", "code", "retry"),
    [
        (APITimeoutError(request=REQUEST), "ai_timeout", True),
        (
            RateLimitError(
                "slow down",
                response=httpx.Response(429, request=REQUEST),
                body={"code": "rate_limit_exceeded"},
            ),
            "ai_rate_limited",
            True,
        ),
        (
            RateLimitError(
                "no credit",
                response=httpx.Response(429, request=REQUEST),
                body={"code": "insufficient_quota"},
            ),
            "ai_budget_exhausted",
            False,
        ),
        (APIConnectionError(request=REQUEST), "ai_provider_error", True),
        (
            InternalServerError("boom", response=httpx.Response(500, request=REQUEST), body=None),
            "ai_provider_error",
            True,
        ),
    ],
)
async def test_provider_failures_become_job_codes_without_provider_text(
    failure: Exception, code: str, retry: bool
) -> None:
    client, _ = _client(failure)

    with pytest.raises(LlmError) as raised:
        await client.complete(system="s", user="u", schema=RESPONSE_SCHEMA)

    assert (raised.value.code, raised.value.retry, str(raised.value)) == (code, retry, code)


def test_the_real_client_is_used_only_with_a_key_and_never_for_demos() -> None:
    def settings(key: str | None) -> AiSettings:
        return AiSettings.model_validate(
            {
                "database_url": "postgresql+asyncpg://unused@localhost/unused",
                "OPENAI_API_KEY": SecretStr(key) if key else None,
            }
        )

    with_key, without_key = llm_clients(settings("sk-test")), llm_clients(settings(None))
    blank = llm_clients(settings(" "))

    assert isinstance(with_key.for_organization(is_demo=False), OpenAiLlmClient)
    assert isinstance(with_key.for_organization(is_demo=True), FakeLlmClient)
    assert without_key.for_organization(is_demo=False) is None
    assert blank.for_organization(is_demo=False) is None
