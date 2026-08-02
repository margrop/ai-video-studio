from packages.planner import StoryPlanner
from packages.subtitle.srt import render_srt


def test_srt_contains_timeline_and_narration() -> None:
    import asyncio

    result = asyncio.run(
        StoryPlanner(provider=None).plan(topic="Synthetic", duration_seconds=15, use_ai=False)
    )
    srt = render_srt(result.plan)

    assert "00:00:00,000 -->" in srt
    assert "Synthetic" in srt
