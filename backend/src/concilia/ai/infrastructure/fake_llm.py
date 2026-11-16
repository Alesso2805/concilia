import json
from collections.abc import Callable, Mapping
from typing import Any

from concilia.ai.application.llm import LlmResult

NO_SUGGESTIONS = json.dumps(
    {"suggestions": [], "no_match_reason": "Sin sugerencias en la demo para este abono."}
)


class FakeLlmClient:
    """Deterministic stand-in for the provider: answers with whatever `answer` returns for
    the user input. Tests script it; demo organizations use it so they never reach the
    provider (rule 7)."""

    model = "fake"

    def __init__(self, answer: Callable[[str], str] | None = None) -> None:
        self._answer = answer or (lambda _user: NO_SUGGESTIONS)
        self.calls: list[str] = []

    async def complete(self, *, system: str, user: str, schema: Mapping[str, Any]) -> LlmResult:
        self.calls.append(user)
        output = self._answer(user)
        return LlmResult(output, self.model, len(system) + len(user), len(output))
