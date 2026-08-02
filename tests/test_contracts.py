import pytest
from pydantic import ValidationError

from packages.contracts.models import CreateJobRequest, Shot, StoryPlan


def test_story_plan_is_versioned_and_timeline_is_valid() -> None:
    plan = StoryPlan(
        title="Synthetic demo",
        summary="A synthetic plan.",
        narration="First shot. Second shot.",
        target_duration_seconds=15,
        shots=[
            Shot(
                id="shot-01",
                start_seconds=0,
                duration_seconds=7.5,
                narration="First shot.",
                visual="A title card.",
            ),
            Shot(
                id="shot-02",
                start_seconds=7.5,
                duration_seconds=7.5,
                narration="Second shot.",
                visual="A summary card.",
            ),
        ],
    )

    assert plan.schema_version == "story-plan-v1"
    assert plan.shots[-1].start_seconds + plan.shots[-1].duration_seconds == 15


def test_public_job_rejects_provider_controls() -> None:
    with pytest.raises(ValidationError):
        CreateJobRequest(topic="synthetic", provider="minimax")


def test_story_plan_rejects_non_shot_sized_or_non_contiguous_clips() -> None:
    with pytest.raises(ValidationError):
        StoryPlan(
            title="Too long",
            summary="A synthetic plan.",
            narration="Narration.",
            target_duration_seconds=15,
            shots=[
                Shot(
                    id="shot-01",
                    start_seconds=0,
                    duration_seconds=15.5,
                    narration="Narration.",
                    visual="A visual.",
                )
            ],
        )
    with pytest.raises(ValidationError):
        StoryPlan(
            title="Gap",
            summary="A synthetic plan.",
            narration="Narration.",
            target_duration_seconds=15,
            shots=[
                Shot(
                    id="shot-01",
                    start_seconds=0,
                    duration_seconds=7.5,
                    narration="First.",
                    visual="A visual.",
                ),
                Shot(
                    id="shot-02",
                    start_seconds=8.5,
                    duration_seconds=6.5,
                    narration="Second.",
                    visual="Another visual.",
                ),
            ],
        )
