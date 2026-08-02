import asyncio
import shutil
import subprocess

import pytest

from packages.contracts.models import CreateJobRequest
from packages.planner import StoryPlanner
from packages.workflow import RenderWorkflow


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None,
    reason="ffmpeg is required for media smoke test",
)
def test_offline_workflow_writes_valid_mp4(tmp_path) -> None:
    result = asyncio.run(
        RenderWorkflow(planner=StoryPlanner()).run(
            CreateJobRequest(topic="Synthetic render", duration_seconds=15, use_ai=False),
            tmp_path,
        )
    )

    assert result.video_path.is_file()
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=format_name,duration",
            "-of",
            "default=noprint_wrappers=1",
            str(result.video_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "format_name=mov,mp4" in probe.stdout
    duration = float(
        next(
            line.split("=", 1)[1]
            for line in probe.stdout.splitlines()
            if line.startswith("duration=")
        )
    )
    assert duration > 10
