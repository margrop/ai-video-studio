"""Server-owned provider wiring and runtime metadata.

Public job input never chooses a model or provider. Environment configuration
is read only when an app or worker constructs the runtime. The returned
registry is safe to expose because it contains identifiers and capabilities,
never credentials or raw provider responses.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from packages.planner import StoryPlanner
from packages.providers import ProviderRegistry
from packages.tts import SilentTTSProvider
from packages.workflow import RenderWorkflow
from providers.minimax import MiniMaxH3Provider, MiniMaxTTSProvider


class _OfflinePlannerProvider:
    provider_id = "deterministic-planner"


class _OfflineVideoProvider:
    provider_id = "offline-renderer"


@dataclass(frozen=True)
class AppRuntime:
    workflow: RenderWorkflow
    providers: ProviderRegistry


def build_runtime() -> AppRuntime:
    registry = ProviderRegistry()

    llm_provider = None
    if os.getenv("AIVS_LLM_API_KEY"):
        llm_provider = MiniMaxH3Provider.from_env()
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

    registry.register(
        _OfflineVideoProvider(),
        kind="video",
        capabilities=("slideshow", "ffmpeg"),
    )

    workflow = RenderWorkflow(
        planner=StoryPlanner(provider=llm_provider),
        tts_provider=tts_provider,
    )
    return AppRuntime(workflow=workflow, providers=registry)


def build_default_workflow() -> RenderWorkflow:
    """Compatibility helper for callers that only need the workflow."""

    return build_runtime().workflow
