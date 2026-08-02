"""Article/topic to video workflow for the Phase 1 CLI and worker."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from inspect import isawaitable
from pathlib import Path
from typing import Any, Protocol

from packages.contracts.models import CreateJobRequest, StoryPlan
from packages.ffmpeg import FFmpegRenderer
from packages.planner import StoryPlanner
from packages.providers import VideoProvider
from packages.storyboard import PromptBuilder
from packages.subtitle import write_srt
from packages.tts import SilentTTSProvider, TTSProvider


class ProgressCallback(Protocol):
    def __call__(
        self,
        stage: str,
        completed_shots: int,
        total_shots: int,
        current_shot: int,
        message: str,
    ) -> Any: ...


async def _notify_progress(
    callback: ProgressCallback | None,
    *,
    stage: str,
    completed_shots: int = 0,
    total_shots: int = 0,
    current_shot: int = 0,
    message: str,
) -> None:
    if callback is None:
        return
    result = callback(stage, completed_shots, total_shots, current_shot, message)
    if isawaitable(result):
        await result


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
        reference_images: tuple[Path, ...] = (),
        prompt_config: Mapping[str, str] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> RenderResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        await _notify_progress(
            progress_callback,
            stage="planning",
            message="正在生成 Story Plan",
        )
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
        await _notify_progress(
            progress_callback,
            stage="narration",
            message="正在生成配音",
        )
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
            shot_paths: list[Path] = []
            total_shots = len(result.plan.shots)
            await _notify_progress(
                progress_callback,
                stage="video",
                total_shots=total_shots,
                message=f"准备生成 {total_shots} 个分镜",
            )
            for index, shot in enumerate(result.plan.shots):
                shot_path = output_dir / f"provider-shot-{index + 1:02d}.mp4"
                await _notify_progress(
                    progress_callback,
                    stage="video",
                    completed_shots=index,
                    total_shots=total_shots,
                    current_shot=index + 1,
                    message=f"正在生成 Shot {index + 1}/{total_shots}",
                )
                await self.video_provider.generate(
                    prompt=shot.prompt,
                    duration_seconds=round(shot.duration_seconds),
                    output_path=shot_path,
                    reference_images=reference_images,
                )
                shot_paths.append(shot_path)
                await _notify_progress(
                    progress_callback,
                    stage="video",
                    completed_shots=index + 1,
                    total_shots=total_shots,
                    current_shot=index + 1,
                    message=f"已完成 Shot {index + 1}/{total_shots}",
                )
            await _notify_progress(
                progress_callback,
                stage="composition",
                completed_shots=total_shots,
                total_shots=total_shots,
                message="正在合成分镜并混入配音",
            )
            await self.renderer.concat_videos_async(
                video_paths=tuple(shot_paths),
                output_path=provider_video_path,
            )
            video_path = await self.renderer.mux_audio_async(
                video_path=provider_video_path,
                audio_path=audio_path,
                output_path=output_dir / "video.mp4",
                duration_seconds=request.duration_seconds,
            )
            video_provider_id = self.video_provider.provider_id
        if self.video_provider is None:
            await _notify_progress(
                progress_callback,
                stage="composition",
                message="正在生成离线视频并混入配音",
            )
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
