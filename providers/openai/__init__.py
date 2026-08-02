"""OpenAI-compatible adapter namespace."""

from __future__ import annotations

from packages.llm import OpenAICompatibleLLMProvider
from packages.providers.http_video import HTTPVideoProvider


class OpenAIVideoProvider(HTTPVideoProvider):
    provider_id = "openai-video"

    @classmethod
    def from_env(cls) -> OpenAIVideoProvider:
        return super().from_env(provider_id=cls.provider_id, env_prefix="AIVS_OPENAI_VIDEO")


__all__ = ["OpenAICompatibleLLMProvider", "OpenAIVideoProvider"]
