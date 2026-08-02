import pytest

from packages.planner import StoryPlanner


@pytest.mark.asyncio
async def test_deterministic_planner_creates_one_minute_timeline() -> None:
    result = await StoryPlanner(provider=None).plan(
        topic="Synthetic topic",
        source_markdown="# Synthetic topic\n\nOne two three four five six.",
        duration_seconds=60,
        use_ai=False,
    )

    assert result.mode == "deterministic"
    assert result.plan.target_duration_seconds == 60
    assert result.plan.shots
    assert result.plan.shots[-1].start_seconds + result.plan.shots[
        -1
    ].duration_seconds == pytest.approx(60)
    assert all(shot.prompt for shot in result.plan.shots)
