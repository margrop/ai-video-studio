"""Provider-neutral LLM interfaces and the OpenAI-compatible transport."""

from .base import LLMProvider, LLMProviderError
from .openai_compatible import OpenAICompatibleLLMProvider

__all__ = ["LLMProvider", "LLMProviderError", "OpenAICompatibleLLMProvider"]
