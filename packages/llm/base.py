"""Small interface for planner models.

The interface intentionally speaks structured JSON rather than exposing a
vendor SDK to the workflow layer.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol


class LLMProviderError(RuntimeError):
    """A safe, user-facing provider failure without raw response content."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class LLMProvider(Protocol):
    provider_id: str

    async def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: Mapping[str, object],
        timeout_seconds: float,
    ) -> dict[str, object]:
        """Generate a JSON object subject to a server-owned schema."""
