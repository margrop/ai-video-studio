"""Provider-neutral extension points.

Adding Kling, Veo or Runway should only require an adapter package and a
server-side registration entry; the workflow must not import those vendors.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import entry_points
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


class VideoProviderError(RuntimeError):
    """Safe provider failure with a retry decision owned by the adapter."""

    def __init__(self, code: str, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class ProviderDescriptor:
    """Safe provider metadata exposed to operators, never credentials."""

    provider_id: str
    kind: str
    capabilities: tuple[str, ...] = ()
    configured: bool = True


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, object] = {}
        self._descriptors: dict[str, ProviderDescriptor] = {}

    def register(
        self,
        provider: object,
        *,
        kind: str = "video",
        capabilities: tuple[str, ...] = (),
        configured: bool = True,
    ) -> None:
        provider_id = getattr(provider, "provider_id", None)
        if not isinstance(provider_id, str) or not provider_id:
            raise ValueError("provider must expose a non-empty provider_id")
        if not kind or kind not in {"llm", "tts", "video"}:
            raise ValueError("provider kind must be llm, tts or video")
        if provider_id in self._providers:
            raise ValueError(f"provider already registered: {provider_id}")
        self._providers[provider_id] = provider
        self._descriptors[provider_id] = ProviderDescriptor(
            provider_id=provider_id,
            kind=kind,
            capabilities=tuple(sorted(set(capabilities))),
            configured=configured,
        )

    def get(self, provider_id: str) -> object:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise KeyError(f"provider is not registered: {provider_id}") from exc

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))

    def descriptors(self) -> tuple[ProviderDescriptor, ...]:
        return tuple(self._descriptors[provider_id] for provider_id in self.ids())

    def select(
        self,
        *,
        kind: str,
        required_capabilities: tuple[str, ...] = (),
        preferred_id: str | None = None,
    ) -> object | None:
        """Select a server-configured provider by capability, not user input."""

        required = set(required_capabilities)
        descriptors = list(self.descriptors())
        if preferred_id:
            descriptors = [
                descriptor for descriptor in descriptors if descriptor.provider_id == preferred_id
            ]
        candidates = [
            descriptor
            for descriptor in descriptors
            if descriptor.kind == kind and required.issubset(descriptor.capabilities)
        ]
        if not candidates:
            return None
        selected = candidates[0]
        return self.get(selected.provider_id)

    def load_entry_points(self, *, group: str = "aivs.video_providers") -> tuple[str, ...]:
        """Load installed provider plugins without importing vendors in the workflow."""

        discovered = entry_points()
        if hasattr(discovered, "select"):
            selected = discovered.select(group=group)
        else:
            selected = discovered.get(group, ())
        loaded: list[str] = []
        for entry_point in selected:
            factory = entry_point.load()
            provider = factory() if isinstance(factory, type) else factory
            capabilities = tuple(getattr(provider, "capabilities", ()))
            self.register(
                provider,
                kind=getattr(provider, "provider_kind", "video"),
                capabilities=capabilities,
            )
            loaded.append(provider.provider_id)
        return tuple(sorted(loaded))
