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


def test_renderer_uses_configured_cjk_font(tmp_path, monkeypatch) -> None:
    font_file = tmp_path / "Chinese Font.ttc"
    font_file.write_bytes(b"synthetic-font")
    monkeypatch.setenv("AIVS_FONT_FILE", str(font_file))

    renderer = FFmpegRenderer()

    assert renderer._resolve_font_file(cjk_required=True) == font_file
    assert renderer._filter_path(font_file).startswith("'")


def test_renderer_reports_missing_configured_font(tmp_path, monkeypatch) -> None:
    missing_font = tmp_path / "missing-font.ttc"
    monkeypatch.setenv("AIVS_FONT_FILE", str(missing_font))

    with pytest.raises(FFmpegError, match="AIVS_FONT_FILE was not found"):
        FFmpegRenderer()._resolve_font_file(cjk_required=True)


def test_renderer_detects_cjk_text() -> None:
    assert FFmpegRenderer._contains_cjk("用一分钟介绍 MCP") is True
    assert FFmpegRenderer._contains_cjk("Introduce MCP") is False


def test_renderer_rejects_cjk_when_no_supported_font_exists(monkeypatch) -> None:
    monkeypatch.setattr(FFmpegRenderer, "_CJK_FONT_CANDIDATES", ())
    monkeypatch.setattr(FFmpegRenderer, "_fontconfig_cjk_font", staticmethod(lambda: None))

    with pytest.raises(FFmpegError, match="No CJK-capable font"):
        FFmpegRenderer()._resolve_font_file(cjk_required=True)
