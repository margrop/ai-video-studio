import asyncio
from uuid import uuid4

from packages.contracts.models import SocialApprovalRequest
from packages.planner import StoryPlanner
from packages.publishing import ApprovalStore, build_social_drafts, write_social_drafts


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


def test_approval_store_keeps_an_auditable_decision_history(tmp_path) -> None:
    store = ApprovalStore(tmp_path / "approvals")
    job_id = uuid4()

    approved = store.decide(
        job_id,
        SocialApprovalRequest(
            platform="wechat",
            decision="approved",
            reviewer="editor",
            note="Reviewed against the source article.",
        ),
    )
    rejected = store.decide(
        job_id,
        SocialApprovalRequest(
            platform="wechat",
            decision="rejected",
            reviewer="editor",
            note="Need a shorter title.",
        ),
    )

    assert [item.approval_id for item in store.list(job_id)] == [
        approved.approval_id,
        rejected.approval_id,
    ]
    assert store.latest(job_id)["wechat"].decision == "rejected"
