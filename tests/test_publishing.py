import asyncio

from packages.planner import StoryPlanner
from packages.publishing import build_social_drafts, write_social_drafts


def test_social_drafts_are_reviewable_and_never_marked_published(tmp_path) -> None:
    result = asyncio.run(
        StoryPlanner().plan(topic="AI 内容流水线", duration_seconds=15, use_ai=False)
    )
    bundle = build_social_drafts(result.plan)
    output = write_social_drafts(result.plan, tmp_path / "social-drafts.json")

    assert bundle.schema_version == "social-drafts-v1"
    assert len(bundle.drafts) == 7
    assert all(draft.requires_human_approval for draft in bundle.drafts)
    assert all(not draft.published for draft in bundle.drafts)
    assert output.is_file()
