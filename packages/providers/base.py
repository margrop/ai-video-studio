"""Provider-neutral extension points.

Adding Kling, Veo or Runway should only require an adapter package and a
server-side registration entry; the workflow must not import those vendors.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class VideoProvider(Protocol):
    provider_id: str

    async def generate(
        self,
        *,
        prompt: str,
        duration_seconds: int,
        output_path: Path,
        reference_images: tuple[Path, ...] = (),
    ) -> Path:
        """Generate a video artifact from a provider-owned prompt."""


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, object] = {}

    def register(self, provider: object) -> None:
        provider_id = getattr(provider, "provider_id", None)
        if not isinstance(provider_id, str) or not provider_id:
            raise ValueError("provider must expose a non-empty provider_id")
        if provider_id in self._providers:
            raise ValueError(f"provider already registered: {provider_id}")
        self._providers[provider_id] = provider

    def get(self, provider_id: str) -> object:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise KeyError(f"provider is not registered: {provider_id}") from exc

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))
