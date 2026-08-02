"""Article/topic to video workflow for the Phase 1 CLI and worker."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from packages.contracts.models import CreateJobRequest, StoryPlan
from packages.ffmpeg import FFmpegRenderer
from packages.planner import StoryPlanner
from packages.providers import VideoProvider
from packages.storyboard import PromptBuilder
from packages.subtitle import write_srt
from packages.tts import SilentTTSProvider, TTSProvider


@dataclass(frozen=True)
class RenderResult:
    plan: StoryPlan
    mode: str
    plan_path: Path
    subtitle_path: Path
    audio_path: Path
    video_path: Path
    video_provider_id: str | None = None
    warnings: tuple[str, ...] = ()


class RenderWorkflow:
    def __init__(
        self,
        *,
        planner: StoryPlanner,
        tts_provider: TTSProvider | None = None,
        renderer: FFmpegRenderer | None = None,
        video_provider: VideoProvider | None = None,
    ) -> None:
        self.planner = planner
        self.tts_provider = tts_provider or SilentTTSProvider()
        self.renderer = renderer or FFmpegRenderer()
        self.video_provider = video_provider

    async def run(
        self,
        request: CreateJobRequest,
        output_dir: Path,
        *,
        character_prompt: str = "",
        prompt_config: Mapping[str, str] | None = None,
    ) -> RenderResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        prompt_builder = PromptBuilder.from_config(prompt_config) if prompt_config else None
        result = await self.planner.plan(
            topic=request.topic,
            source_markdown=request.source_markdown,
            duration_seconds=request.duration_seconds,
            language=request.language,
            voice=request.voice,
            use_ai=request.use_ai,
            character_prompt=character_prompt,
            prompt_builder=prompt_builder,
        )
        plan_path = output_dir / "story-plan.json"
        plan_path.write_text(result.plan.model_dump_json(indent=2), encoding="utf-8")
        subtitle_path = write_srt(result.plan, output_dir / "subtitles.srt")
        audio_path = await self.tts_provider.synthesize(
            text=result.plan.narration,
            voice=request.voice,
            language=request.language,
            output_path=output_dir / "narration.wav",
            timeout_seconds=45,
        )
        video_provider_id = None
        if self.video_provider is None:
            video_path = await self.renderer.render_slideshow_async(
                plan=result.plan,
                output_path=output_dir / "video.mp4",
                audio_path=audio_path,
            )
        else:
            provider_video_path = output_dir / "provider-video.mp4"
            provider_prompt = "\n".join(shot.prompt for shot in result.plan.shots)
            await self.video_provider.generate(
                prompt=provider_prompt,
                duration_seconds=request.duration_seconds,
                output_path=provider_video_path,
            )
            video_path = await self.renderer.mux_audio_async(
                video_path=provider_video_path,
                audio_path=audio_path,
                output_path=output_dir / "video.mp4",
                duration_seconds=request.duration_seconds,
            )
            video_provider_id = self.video_provider.provider_id
        return RenderResult(
            plan=result.plan,
            mode=result.mode,
            plan_path=plan_path,
            subtitle_path=subtitle_path,
            audio_path=audio_path,
            video_path=video_path,
            video_provider_id=video_provider_id,
            warnings=result.warnings,
        )
