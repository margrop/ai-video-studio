"""Server-owned provider wiring.

Public job input never chooses a model or provider. Environment configuration
is read only when an app/worker constructs its runtime.
"""

from __future__ import annotations

import os

from packages.planner import StoryPlanner
from packages.tts import SilentTTSProvider
from packages.workflow import RenderWorkflow
from providers.minimax import MiniMaxH3Provider, MiniMaxTTSProvider


def build_default_workflow() -> RenderWorkflow:
    llm_provider = None
    if os.getenv("AIVS_LLM_API_KEY"):
        llm_provider = MiniMaxH3Provider.from_env()

    tts_provider = SilentTTSProvider()
    if all(os.getenv(key) for key in ("AIVS_TTS_BASE_URL", "AIVS_TTS_API_KEY", "AIVS_TTS_MODEL")):
        tts_provider = MiniMaxTTSProvider.from_env()

    return RenderWorkflow(
        planner=StoryPlanner(provider=llm_provider),
        tts_provider=tts_provider,
    )
