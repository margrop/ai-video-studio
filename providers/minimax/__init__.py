"""MiniMax adapters.

The H3 adapter is an OpenAI-compatible text planner adapter. Video generation
is intentionally a separate capability so the content workflow can use local
FFmpeg, a hosted video model, or a future MiniMax video endpoint.
"""

from __future__ import annotations

import os

from packages.llm import OpenAICompatibleLLMProvider
from packages.providers.http_video import HTTPVideoProvider
from packages.tts.openai_compatible import OpenAICompatibleTTSProvider


class MiniMaxH3Provider(OpenAICompatibleLLMProvider):
    provider_id = "minimax-h3"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str = "MiniMax-H3",
    ) -> None:
        super().__init__(
            provider_id=self.provider_id,
            base_url=base_url,
            api_key=api_key,
            model=model,
        )

    @classmethod
    def from_env(cls) -> MiniMaxH3Provider:
        return cls(
            base_url=os.getenv("AIVS_LLM_BASE_URL", "http://127.0.0.1:3001/v1"),
            api_key=os.getenv("AIVS_LLM_API_KEY", ""),
            model=os.getenv("AIVS_LLM_MODEL", "MiniMax-H3"),
        )


class MiniMaxTTSProvider(OpenAICompatibleTTSProvider):
    provider_id = "minimax-tts"

    @classmethod
    def from_env(cls) -> MiniMaxTTSProvider:
        return cls(
            base_url=os.getenv("AIVS_TTS_BASE_URL", ""),
            api_key=os.getenv("AIVS_TTS_API_KEY", ""),
            model=os.getenv("AIVS_TTS_MODEL", ""),
        )


class MiniMaxVideoProvider(HTTPVideoProvider):
    """Transport-compatible MiniMax video scaffold.

    The endpoint contract remains server-configured until the vendor-specific
    request and response shape is verified. It deliberately reuses only the
    generic submit/poll/download boundary.
    """

    provider_id = "minimax-video"

    @classmethod
    def from_env(cls) -> MiniMaxVideoProvider:
        return super().from_env(provider_id=cls.provider_id, env_prefix="AIVS_MINIMAX_VIDEO")


__all__ = ["MiniMaxH3Provider", "MiniMaxTTSProvider", "MiniMaxVideoProvider"]
