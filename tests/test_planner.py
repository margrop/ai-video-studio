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
    assert len(result.plan.shots) == 8
    assert all(4 <= shot.duration_seconds <= 15 for shot in result.plan.shots)


@pytest.mark.asyncio
async def test_deterministic_planner_honors_english_language() -> None:
    result = await StoryPlanner(provider=None).plan(
        topic="MCP",
        duration_seconds=15,
        language="en",
        use_ai=False,
    )

    assert result.plan.language == "en"
    assert all(
        "\u4e00" > char or char > "\u9fff" for shot in result.plan.shots for char in shot.visual
    )
