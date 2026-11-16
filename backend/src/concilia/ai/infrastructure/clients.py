from concilia.ai.application.llm import LlmClient
from concilia.ai.infrastructure.openai_llm import OpenAiLlmClient
from concilia.shared.infrastructure.settings import AiSettings


class LlmClients:
    """The provider for regular organizations (ADR-0006), or none without a key; demo
    organizations replay recordings instead and never reach it."""

    def __init__(self, real: LlmClient | None) -> None:
        self._real = real

    def provider(self) -> LlmClient | None:
        return self._real


def llm_clients(settings: AiSettings) -> LlmClients:
    key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
    real = OpenAiLlmClient(key, settings.ai_model) if key.strip() else None
    return LlmClients(real=real)
