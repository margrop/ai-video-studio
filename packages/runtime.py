"""Server-owned provider wiring and runtime metadata.

Public job input never chooses a model or provider. Environment configuration
is read only when an app or worker constructs the runtime. The returned
registry is safe to expose because it contains identifiers and capabilities,
never credentials or raw provider responses.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from packages.library import AssetCatalog, CharacterCatalog, TemplateCatalog, build_catalogs
from packages.planner import StoryPlanner
from packages.providers import ProviderRegistry, VideoProvider
from packages.providers.http_video import HTTPVideoProvider
from packages.publishing import PublisherRegistry
from packages.tts import SilentTTSProvider
from packages.workflow import RenderWorkflow
from providers.kling import KlingVideoProvider
from providers.minimax import MiniMaxLLMProvider, MiniMaxTTSProvider, MiniMaxVideoProvider
from providers.openai import OpenAIVideoProvider
from providers.runway import RunwayVideoProvider
from providers.veo import GoogleVeoVideoProvider


class _OfflinePlannerProvider:
    provider_id = "deterministic-planner"


class _OfflineVideoProvider:
    provider_id = "offline-renderer"


_VENDOR_VIDEO_FACTORIES = {
    "minimax-video": MiniMaxVideoProvider,
    "kling": KlingVideoProvider,
    "google-veo": GoogleVeoVideoProvider,
    "runway": RunwayVideoProvider,
    "openai-video": OpenAIVideoProvider,
}


@dataclass(frozen=True)
class AppRuntime:
    workflow: RenderWorkflow
    providers: ProviderRegistry
    video_provider: VideoProvider | None
    assets: AssetCatalog
    characters: CharacterCatalog
    templates: TemplateCatalog
    publishers: PublisherRegistry = field(default_factory=PublisherRegistry)


def build_runtime(library_root: Path | None = None) -> AppRuntime:
    registry = ProviderRegistry()
    registry.load_entry_points()
    base_library_root = library_root or Path(os.getenv("AIVS_STORAGE_ROOT", ".aivs")) / "library"
    assets, characters = build_catalogs(base_library_root)
    templates = TemplateCatalog(Path(__file__).parents[1] / "templates")

    llm_provider = None
    if os.getenv("AIVS_LLM_API_KEY"):
        llm_provider = MiniMaxLLMProvider.from_env()
        registry.register(
            llm_provider,
            kind="llm",
            capabilities=("structured-json", "story-planning"),
        )
    else:
        registry.register(
            _OfflinePlannerProvider(),
            kind="llm",
            capabilities=("deterministic-fallback", "story-planning"),
        )

    tts_provider = SilentTTSProvider()
    registry.register(
        tts_provider,
        kind="tts",
        capabilities=("offline-audio",),
    )
    if all(os.getenv(key) for key in ("AIVS_TTS_BASE_URL", "AIVS_TTS_API_KEY", "AIVS_TTS_MODEL")):
        tts_provider = MiniMaxTTSProvider.from_env()
        registry.register(
            tts_provider,
            kind="tts",
            capabilities=("speech-synthesis",),
        )

    video_provider: VideoProvider | None = None
    configured_video_id = os.getenv("AIVS_VIDEO_PROVIDER", "").strip()
    if configured_video_id and configured_video_id in registry.ids():
        candidate = registry.get(configured_video_id)
        if hasattr(candidate, "generate"):
            video_provider = candidate  # type: ignore[assignment]
    elif configured_video_id in _VENDOR_VIDEO_FACTORIES:
        candidate = _VENDOR_VIDEO_FACTORIES[configured_video_id].from_env()
        if all((candidate.base_url, candidate.api_key, candidate.model)):
            video_provider = candidate
            registry.register(
                video_provider,
                kind="video",
                capabilities=tuple(candidate.capabilities),
            )
        else:
            registry.register(
                _OfflineVideoProvider(),
                kind="video",
                capabilities=("slideshow", "ffmpeg"),
            )
    elif configured_video_id and all(
        os.getenv(key) for key in ("AIVS_VIDEO_BASE_URL", "AIVS_VIDEO_API_KEY", "AIVS_VIDEO_MODEL")
    ):
        video_provider = HTTPVideoProvider.from_env(provider_id=configured_video_id)
        registry.register(
            video_provider,
            kind="video",
            capabilities=("async-generation", "remote-download", "shot-generation"),
        )
    else:
        registry.register(
            _OfflineVideoProvider(),
            kind="video",
            capabilities=("slideshow", "ffmpeg"),
        )

    workflow = RenderWorkflow(
        planner=StoryPlanner(provider=llm_provider),
        tts_provider=tts_provider,
        video_provider=video_provider,
    )
    return AppRuntime(
        workflow=workflow,
        providers=registry,
        video_provider=video_provider,
        assets=assets,
        characters=characters,
        templates=templates,
        publishers=PublisherRegistry(),
    )


def build_default_workflow() -> RenderWorkflow:
    """Compatibility helper for callers that only need the workflow."""

    return build_runtime().workflow
