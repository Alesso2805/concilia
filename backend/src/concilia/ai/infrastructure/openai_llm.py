from collections.abc import Mapping
from typing import Any

from openai import APIConnectionError, APIError, APITimeoutError, AsyncOpenAI, RateLimitError

from concilia.ai.application.llm import LlmError, LlmResult

TIMEOUT_SECONDS = 30.0
MAX_OUTPUT_TOKENS = 2_000


class OpenAiLlmClient:
    """The provider of ADR-0006 through the Responses API: strict structured output, nothing
    stored on the provider's side, and no SDK retries because the job queue owns them."""

    def __init__(self, api_key: str, model: str, *, client: AsyncOpenAI | None = None) -> None:
        self._client = client or AsyncOpenAI(
            api_key=api_key, max_retries=0, timeout=TIMEOUT_SECONDS
        )
        self._model = model

    async def complete(self, *, system: str, user: str, schema: Mapping[str, Any]) -> LlmResult:
        try:
            response = await self._client.responses.create(
                model=self._model,
                instructions=system,
                input=user,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "concilia_suggestions",
                        "schema": dict(schema),
                        "strict": True,
                    }
                },
                reasoning={"effort": "low"},
                max_output_tokens=MAX_OUTPUT_TOKENS,
                store=False,
            )
        except APITimeoutError:
            raise LlmError("ai_timeout", retry=True) from None
        except RateLimitError as error:
            if error.code == "insufficient_quota":
                raise LlmError("ai_budget_exhausted", retry=False) from None
            raise LlmError("ai_rate_limited", retry=True) from None
        except APIConnectionError, APIError:
            raise LlmError("ai_provider_error", retry=True) from None
        usage = response.usage
        return LlmResult(
            output=response.output_text,
            model=response.model,
            input_tokens=usage.input_tokens if usage else 0,
            output_tokens=usage.output_tokens if usage else 0,
        )
