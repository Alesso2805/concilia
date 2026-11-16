from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

__all__ = ["LlmClient", "LlmError", "LlmResult"]


@dataclass(frozen=True)
class LlmResult:
    output: str
    model: str
    input_tokens: int
    output_tokens: int


class LlmError(Exception):
    """A provider failure with a job error code: `ai_timeout`, `ai_rate_limited`,
    `ai_budget_exhausted` or `ai_provider_error` (ADR-0006). Never carries provider text."""

    def __init__(self, code: str, *, retry: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retry = retry


class LlmClient(Protocol):
    async def complete(self, *, system: str, user: str, schema: Mapping[str, Any]) -> LlmResult: ...
