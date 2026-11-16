from concilia.ai.application.llm import LlmClient
from concilia.ai.infrastructure.fake_llm import FakeLlmClient
from concilia.ai.infrastructure.openai_llm import OpenAiLlmClient
from concilia.shared.infrastructure.settings import AiSettings


class LlmClients:
    """Which client serves an organization (ADR-0006): demo organizations always get the fake,
    which never reaches the provider; others get the real client, or none without a key."""

    def __init__(self, real: LlmClient | None, demo: LlmClient | None = None) -> None:
        self._real = real
        self._demo = demo or FakeLlmClient()

    def for_organization(self, is_demo: bool) -> LlmClient | None:
        return self._demo if is_demo else self._real


def llm_clients(settings: AiSettings) -> LlmClients:
    key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
    real = OpenAiLlmClient(key, settings.ai_model) if key.strip() else None
    return LlmClients(real=real)
