"""MiniMax adapters for the NewAPI-backed planner, TTS and native H3 video."""

from __future__ import annotations

import os

from packages.llm import OpenAICompatibleLLMProvider
from packages.tts.openai_compatible import OpenAICompatibleTTSProvider

from .video import MiniMaxH3VideoProvider


class MiniMaxLLMProvider(OpenAICompatibleLLMProvider):
    """OpenAI-compatible text model, normally routed through NewAPI."""

    provider_id = "minimax-llm"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str = "minimax-latest",
    ) -> None:
        super().__init__(
            provider_id=self.provider_id,
            base_url=base_url,
            api_key=api_key,
            model=model,
        )

    @classmethod
    def from_env(cls) -> MiniMaxLLMProvider:
        return cls(
            base_url=os.getenv("AIVS_LLM_BASE_URL", "http://127.0.0.1:3001/v1"),
            api_key=os.getenv("AIVS_LLM_API_KEY", ""),
            model=os.getenv("AIVS_LLM_MODEL", "minimax-latest"),
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


# Backwards-compatible import name. H3 is a video model; the planner itself
# uses the text model selected by AIVS_LLM_MODEL through the configured gateway.
MiniMaxH3Provider = MiniMaxLLMProvider
MiniMaxVideoProvider = MiniMaxH3VideoProvider


__all__ = [
    "MiniMaxH3Provider",
    "MiniMaxH3VideoProvider",
    "MiniMaxLLMProvider",
    "MiniMaxTTSProvider",
    "MiniMaxVideoProvider",
]
