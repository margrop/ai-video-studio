from __future__ import annotations

import subprocess

import pytest

from packages.ffmpeg import FFmpegError, FFmpegRenderer


def test_renderer_uses_explicit_ffmpeg_environment_path(monkeypatch) -> None:
    monkeypatch.setenv("AIVS_FFMPEG_BINARY", "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg")

    assert FFmpegRenderer().ffmpeg_binary == "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"


def test_renderer_reports_missing_drawtext_filter(monkeypatch) -> None:
    renderer = FFmpegRenderer(ffmpeg_binary="ffmpeg")
    monkeypatch.setattr("packages.ffmpeg.renderer.shutil.which", lambda _: "/usr/bin/ffmpeg")

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="\nFilters:\n ... null V->V Pass through input.\n",
            stderr="",
        )

    monkeypatch.setattr("packages.ffmpeg.renderer.subprocess.run", fake_run)

    with pytest.raises(FFmpegError, match="drawtext.*ffmpeg-full"):
        renderer._require_filter("drawtext")
