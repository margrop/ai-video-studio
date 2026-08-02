"""Generate deterministic SRT without any provider dependency."""

from __future__ import annotations

from pathlib import Path

from packages.contracts.models import StoryPlan


def _timestamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds_part, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds_part:02d},{millis:03d}"


def render_srt(plan: StoryPlan) -> str:
    entries: list[str] = []
    for index, shot in enumerate(plan.shots, start=1):
        start = shot.start_seconds
        end = min(plan.target_duration_seconds, start + shot.duration_seconds)
        entries.append(f"{index}\n{_timestamp(start)} --> {_timestamp(end)}\n{shot.narration}\n")
    return "\n".join(entries)


def write_srt(plan: StoryPlan, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_srt(plan), encoding="utf-8")
    return path
