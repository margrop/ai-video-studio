import asyncio
from uuid import uuid4

from packages.contracts.models import SocialApprovalRequest, SocialDraft
from packages.planner import StoryPlanner
from packages.publishing import (
    ApprovalStore,
    AuditStore,
    PublisherRegistry,
    PublishingService,
    build_social_drafts,
    write_social_drafts,
)


class FakePublisher:
    publisher_id = "fake-wechat"
    platform = "wechat"

    def __init__(self, *, error: str | None = None) -> None:
        self.error = error
        self.calls = 0

    async def publish(self, draft: SocialDraft, *, video_path=None) -> str:
        self.calls += 1
        if self.error:
            raise RuntimeError(self.error)
        return f"external-{draft.platform}"


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


def test_publishing_service_defaults_to_safe_dry_run(tmp_path) -> None:
    approvals = ApprovalStore(tmp_path / "approvals")
    audit = AuditStore(tmp_path / "audit")
    publisher = FakePublisher()
    registry = PublisherRegistry()
    registry.register(publisher)
    service = PublishingService(
        approvals=approvals,
        audit=audit,
        publishers=registry,
        enabled=True,
    )
    job_id = uuid4()
    draft = SocialDraft(platform="wechat", title="Title", body="Body")

    result = asyncio.run(service.publish(job_id=job_id, draft=draft, dry_run=True, actor="codex"))

    assert result.status == "dry_run"
    assert result.approved is False
    assert publisher.calls == 0
    assert audit.list(job_id)[0].action == "publish_dry_run"


def test_publishing_service_requires_approval_and_records_outcomes(tmp_path) -> None:
    approvals = ApprovalStore(tmp_path / "approvals")
    audit = AuditStore(tmp_path / "audit")
    publisher = FakePublisher()
    registry = PublisherRegistry()
    registry.register(publisher)
    service = PublishingService(
        approvals=approvals,
        audit=audit,
        publishers=registry,
        enabled=True,
    )
    job_id = uuid4()
    draft = SocialDraft(platform="wechat", title="Title", body="Body")

    blocked = asyncio.run(service.publish(job_id=job_id, draft=draft, dry_run=False, actor="agent"))
    assert blocked.status == "blocked"
    assert publisher.calls == 0

    approvals.decide(
        job_id,
        SocialApprovalRequest(platform="wechat", decision="approved", reviewer="editor"),
    )
    published = asyncio.run(
        service.publish(job_id=job_id, draft=draft, dry_run=False, actor="editor")
    )

    assert published.status == "published"
    assert published.external_id == "external-wechat"
    assert publisher.calls == 1
    assert [event.action for event in audit.list(job_id)] == [
        "publish_blocked",
        "publish_succeeded",
    ]


def test_publishing_service_redacts_provider_errors(tmp_path) -> None:
    approvals = ApprovalStore(tmp_path / "approvals")
    audit = AuditStore(tmp_path / "audit")
    publisher = FakePublisher(error="authorization=super-secret provider rejected request")
    registry = PublisherRegistry()
    registry.register(publisher)
    service = PublishingService(
        approvals=approvals,
        audit=audit,
        publishers=registry,
        enabled=True,
    )
    job_id = uuid4()
    approvals.decide(
        job_id,
        SocialApprovalRequest(platform="wechat", decision="approved", reviewer="editor"),
    )

    result = asyncio.run(
        service.publish(
            job_id=job_id,
            draft=SocialDraft(platform="wechat", title="Title", body="Body"),
            dry_run=False,
        )
    )

    assert result.status == "failed"
    assert "super-secret" not in result.message
    assert "authorization=[REDACTED]" in result.message
