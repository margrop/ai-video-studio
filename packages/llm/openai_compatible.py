"""Minimal OpenAI-compatible chat transport used by MiniMax and other adapters."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

import httpx

from .base import LLMProviderError


def _extract_json(text: str) -> dict[str, object]:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.I)
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise LLMProviderError(
            "invalid_provider_response", "LLM output was not valid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise LLMProviderError("invalid_provider_response", "LLM output must be a JSON object")
    return value


class OpenAICompatibleLLMProvider:
    """A provider adapter with no provider-specific fields in the workflow API."""

    def __init__(
        self,
        *,
        provider_id: str,
        base_url: str,
        api_key: str,
        model: str,
    ) -> None:
        self.provider_id = provider_id
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    async def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: Mapping[str, object],
        timeout_seconds: float,
    ) -> dict[str, object]:
        if not self.api_key:
            raise LLMProviderError("provider_unavailable", "LLM API key is not configured")

        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": 0.3,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise LLMProviderError("provider_timeout", "LLM request timed out") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMProviderError("provider_unavailable", "LLM request failed") from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError(
                "invalid_provider_response", "LLM response shape was invalid"
            ) from exc
        if not isinstance(content, str):
            raise LLMProviderError("invalid_provider_response", "LLM response content was not text")
        # The schema is included in the prompt by the planner. Keeping this
        # argument in the adapter contract makes server-side schema binding
        # explicit without trusting a client-provided schema.
        _ = schema
        return _extract_json(content)
