from __future__ import annotations

import asyncio
from pathlib import Path

from packages.contracts.models import CreateJobRequest
from packages.planner import StoryPlanner
from packages.workflow import RenderWorkflow


class FakeTTS:
    provider_id = "fake-tts"

    async def synthesize(self, *, text, voice, language, output_path, timeout_seconds):
        _ = text, voice, language, timeout_seconds
        output_path.write_bytes(b"wav")
        return output_path


class RecordingVideoProvider:
    provider_id = "recording-video"

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, Path]] = []

    async def generate(self, *, prompt, duration_seconds, output_path, reference_images=()):
        _ = reference_images
        self.calls.append((prompt, duration_seconds, output_path))
        output_path.write_bytes(b"shot-mp4")
        return output_path


class FakeRenderer:
    def __init__(self) -> None:
        self.concat_calls: list[tuple[tuple[Path, ...], Path]] = []
        self.mux_calls: list[tuple[Path, Path, Path, int]] = []

    async def concat_videos_async(self, *, video_paths, output_path):
        self.concat_calls.append((video_paths, output_path))
        output_path.write_bytes(b"joined-mp4")
        return output_path

    async def mux_audio_async(self, *, video_path, audio_path, output_path, duration_seconds):
        self.mux_calls.append((video_path, audio_path, output_path, duration_seconds))
        output_path.write_bytes(b"final-mp4")
        return output_path


def test_provider_workflow_generates_one_clip_per_story_shot(tmp_path) -> None:
    provider = RecordingVideoProvider()
    renderer = FakeRenderer()
    updates: list[tuple[str, int, int, int, str]] = []

    def on_progress(stage, completed_shots, total_shots, current_shot, message):
        updates.append((stage, completed_shots, total_shots, current_shot, message))

    result = asyncio.run(
        RenderWorkflow(
            planner=StoryPlanner(),
            tts_provider=FakeTTS(),
            renderer=renderer,
            video_provider=provider,
        ).run(
            CreateJobRequest(topic="Shot based video", duration_seconds=60, use_ai=False),
            tmp_path,
            progress_callback=on_progress,
        )
    )

    assert len(provider.calls) == 8
    assert [duration for _prompt, duration, _path in provider.calls] == [8] * 8
    assert all(prompt for prompt, _duration, _path in provider.calls)
    assert len(renderer.concat_calls) == 1
    assert len(renderer.concat_calls[0][0]) == 8
    assert renderer.mux_calls[0][3] == 60
    assert result.video_path.read_bytes() == b"final-mp4"
    assert updates[0][0] == "planning"
    assert updates[-1][0] == "composition"
    assert [update[1] for update in updates if update[0] == "video"][-1] == 8
