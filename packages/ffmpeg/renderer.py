"""Render a provider-neutral plan into a small, reviewable MP4 artifact."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from packages.contracts.models import StoryPlan


class FFmpegError(RuntimeError):
    """FFmpeg is unavailable or refused a render."""


class FFmpegRenderer:
    _CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
    _CJK_FONT_CANDIDATES = (
        Path("/System/Library/Fonts/PingFang.ttc"),
        Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf"),
        Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
    )

    def __init__(
        self,
        *,
        ffmpeg_binary: str = "ffmpeg",
        font_file: Path | str | None = None,
    ) -> None:
        configured_binary = os.getenv("AIVS_FFMPEG_BINARY", "").strip()
        self.ffmpeg_binary = configured_binary or ffmpeg_binary
        configured_font = os.getenv("AIVS_FONT_FILE", "").strip()
        selected_font = configured_font or font_file
        self.font_file = Path(selected_font).expanduser() if selected_font else None

    def _require_ffmpeg(self) -> None:
        if shutil.which(self.ffmpeg_binary) is None:
            raise FFmpegError(f"{self.ffmpeg_binary} was not found in PATH")

    def _require_filter(self, filter_name: str) -> None:
        """Fail early with an actionable message when a build lacks a filter."""

        try:
            completed = subprocess.run(
                [self.ffmpeg_binary, "-hide_banner", "-filters"],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except FileNotFoundError as exc:
            raise FFmpegError(f"{self.ffmpeg_binary} was not found in PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise FFmpegError("FFmpeg capability check timed out") from exc
        except subprocess.CalledProcessError as exc:
            raise FFmpegError("FFmpeg capability check failed") from exc

        output = f"{completed.stdout}\n{completed.stderr}"
        filter_pattern = rf"(?m)^\s*[A-Za-z.]+\s+{re.escape(filter_name)}\s+"
        if re.search(filter_pattern, output) is None:
            hint = (
                "Install a complete FFmpeg build with libfreetype and libharfbuzz "
                "(macOS: brew install ffmpeg-full), then set AIVS_FFMPEG_BINARY "
                "to its absolute path."
            )
            raise FFmpegError(f"FFmpeg filter '{filter_name}' is unavailable. {hint}")

    def _run(self, args: list[str]) -> None:
        try:
            completed = subprocess.run(
                args,
                check=True,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except FileNotFoundError as exc:
            raise FFmpegError(f"{self.ffmpeg_binary} was not found in PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise FFmpegError("FFmpeg render timed out") from exc
        except subprocess.CalledProcessError as exc:
            # Do not expose a full command line or arbitrary provider text in
            # API errors. Keep only a short, non-secret diagnostic.
            detail = (exc.stderr or "").strip().splitlines()[-1:]
            raise FFmpegError(f"FFmpeg failed: {' '.join(detail)[:300]}") from exc
        _ = completed

    @staticmethod
    def _concat_manifest_path(path: Path) -> str:
        return path.as_posix().replace("'", "'\\''")

    @staticmethod
    def _filter_path(path: Path) -> str:
        escaped = path.as_posix().replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
        return f"'{escaped}'"

    @classmethod
    def _contains_cjk(cls, text: str) -> bool:
        return cls._CJK_PATTERN.search(text) is not None

    @staticmethod
    def _fontconfig_cjk_font() -> Path | None:
        font_list = shutil.which("fc-list")
        if font_list is None:
            return None
        try:
            completed = subprocess.run(
                [font_list, "-f", "%{file}\\n", ":lang=zh-cn"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        for line in completed.stdout.splitlines():
            candidate = Path(line.strip())
            if candidate.is_file():
                return candidate
        return None

    def _resolve_font_file(self, *, cjk_required: bool) -> Path | None:
        if self.font_file is not None:
            if not self.font_file.is_file():
                raise FFmpegError(f"Configured AIVS_FONT_FILE was not found: {self.font_file}")
            return self.font_file

        if cjk_required:
            for candidate in self._CJK_FONT_CANDIDATES:
                if candidate.is_file():
                    return candidate
            matched = self._fontconfig_cjk_font()
            if matched is not None:
                return matched
            raise FFmpegError(
                "No CJK-capable font was found. Set AIVS_FONT_FILE to a Chinese font "
                "(macOS: /System/Library/Fonts/PingFang.ttc)."
            )
        return None

    def render_slideshow(
        self,
        *,
        plan: StoryPlan,
        output_path: Path,
        audio_path: Path | None = None,
    ) -> Path:
        self._require_ffmpeg()
        self._require_filter("drawtext")
        cjk_required = self._contains_cjk(plan.title) or any(
            self._contains_cjk(shot.visual) for shot in plan.shots
        )
        font_file = self._resolve_font_file(cjk_required=cjk_required)
        font_option = f":fontfile={self._filter_path(font_file)}" if font_file else ""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="aivs-render-") as temp_dir:
            workspace = Path(temp_dir)
            segment_paths: list[Path] = []
            palette = ["16213e", "0f3460", "533483", "1b5e20", "7b341e"]
            for index, shot in enumerate(plan.shots):
                text_path = workspace / f"shot-{index:02d}.txt"
                text_path.write_text(f"{plan.title}\n\n{shot.visual}", encoding="utf-8")
                segment = workspace / f"segment-{index:02d}.mp4"
                segment_paths.append(segment)
                drawtext = (
                    f"drawtext=fontcolor=white:fontsize=46:line_spacing=12:"
                    f"textfile={self._filter_path(text_path)}{font_option}:"
                    f"x=(w-text_w)/2:y=(h-text_h)/2"
                )
                self._run(
                    [
                        self.ffmpeg_binary,
                        "-y",
                        "-f",
                        "lavfi",
                        "-i",
                        (
                            f"color=c=0x{palette[index % len(palette)]}:"
                            f"s=1080x1920:r=30:d={shot.duration_seconds}"
                        ),
                        "-vf",
                        drawtext,
                        "-an",
                        "-c:v",
                        "libx264",
                        "-pix_fmt",
                        "yuv420p",
                        "-movflags",
                        "+faststart",
                        str(segment),
                    ]
                )

            concat_file = workspace / "concat.txt"
            concat_file.write_text(
                "\n".join(f"file '{segment.as_posix()}'" for segment in segment_paths),
                encoding="utf-8",
            )
            silent_video = workspace / "video.mp4"
            self._run(
                [
                    self.ffmpeg_binary,
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(concat_file),
                    "-c",
                    "copy",
                    str(silent_video),
                ]
            )
            if audio_path is None:
                shutil.copyfile(silent_video, output_path)
            else:
                self._run(
                    [
                        self.ffmpeg_binary,
                        "-y",
                        "-i",
                        str(silent_video),
                        "-i",
                        str(audio_path),
                        "-filter_complex",
                        "[1:a]apad[audio]",
                        "-map",
                        "0:v:0",
                        "-map",
                        "[audio]",
                        "-t",
                        str(plan.target_duration_seconds),
                        "-c:v",
                        "copy",
                        "-c:a",
                        "aac",
                        "-movflags",
                        "+faststart",
                        str(output_path),
                    ]
                )
        return output_path

    async def render_slideshow_async(
        self,
        *,
        plan: StoryPlan,
        output_path: Path,
        audio_path: Path | None = None,
    ) -> Path:
        return await asyncio.to_thread(
            self.render_slideshow,
            plan=plan,
            output_path=output_path,
            audio_path=audio_path,
        )

    def concat_videos(self, *, video_paths: tuple[Path, ...], output_path: Path) -> Path:
        """Join provider-generated shot clips into one silent video.

        Clips are re-encoded at the composition boundary instead of assuming
        that every vendor returns identical codec and time-base settings.
        Provider audio is intentionally discarded; the narration track is
        attached once after the shot list has been joined.
        """

        self._require_ffmpeg()
        if not video_paths:
            raise FFmpegError("no provider shot videos were generated")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="aivs-concat-") as temp_dir:
            concat_file = Path(temp_dir) / "concat.txt"
            concat_file.write_text(
                "\n".join(f"file '{self._concat_manifest_path(path)}'" for path in video_paths),
                encoding="utf-8",
            )
            self._run(
                [
                    self.ffmpeg_binary,
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(concat_file),
                    "-an",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    str(output_path),
                ]
            )
        return output_path

    async def concat_videos_async(
        self,
        *,
        video_paths: tuple[Path, ...],
        output_path: Path,
    ) -> Path:
        return await asyncio.to_thread(
            self.concat_videos,
            video_paths=video_paths,
            output_path=output_path,
        )

    def mux_audio(
        self,
        *,
        video_path: Path,
        audio_path: Path,
        output_path: Path,
        duration_seconds: int,
    ) -> Path:
        """Attach deterministic narration to a provider-generated video."""

        self._require_ffmpeg()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._run(
            [
                self.ffmpeg_binary,
                "-y",
                "-i",
                str(video_path),
                "-i",
                str(audio_path),
                "-filter_complex",
                "[1:a]apad[audio]",
                "-map",
                "0:v:0",
                "-map",
                "[audio]",
                "-t",
                str(duration_seconds),
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
        )
        return output_path

    async def mux_audio_async(
        self,
        *,
        video_path: Path,
        audio_path: Path,
        output_path: Path,
        duration_seconds: int,
    ) -> Path:
        return await asyncio.to_thread(
            self.mux_audio,
            video_path=video_path,
            audio_path=audio_path,
            output_path=output_path,
            duration_seconds=duration_seconds,
        )
