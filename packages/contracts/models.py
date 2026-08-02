"""Stable, provider-neutral contracts for the first pipeline slice."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    """Reject unknown fields at every public boundary."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Shot(StrictModel):
    id: str = Field(min_length=1, max_length=64)
    start_seconds: float = Field(ge=0, le=3600)
    duration_seconds: float = Field(ge=4, le=15)
    narration: str = Field(min_length=1, max_length=2000)
    visual: str = Field(min_length=1, max_length=1000)
    camera: str = Field(default="medium shot", max_length=300)
    prompt: str = Field(default="", max_length=4000)


ShotRenderStatus = Literal["pending", "running", "succeeded", "failed"]


class ShotRenderRecord(StrictModel):
    shot_id: str = Field(min_length=1, max_length=64)
    index: int = Field(ge=1, le=30)
    duration_seconds: int = Field(ge=4, le=15)
    prompt_sha256: str = Field(min_length=64, max_length=64)
    status: ShotRenderStatus = "pending"
    output_path: str = Field(min_length=1, max_length=200)
    error_message: str = Field(default="", max_length=300)


class ShotManifest(StrictModel):
    schema_version: Literal["shot-manifest-v1"] = "shot-manifest-v1"
    plan_fingerprint: str = Field(min_length=64, max_length=64)
    provider_id: str = Field(min_length=1, max_length=100)
    shots: list[ShotRenderRecord] = Field(min_length=1, max_length=30)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StoryPlan(StrictModel):
    """The shared output of planning, independent of a video provider."""

    schema_version: Literal["story-plan-v1"] = "story-plan-v1"
    plan_id: UUID = Field(default_factory=uuid4)
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=1000)
    language: str = Field(default="zh-CN", min_length=2, max_length=20)
    voice: str = Field(default="neutral", min_length=1, max_length=100)
    target_duration_seconds: int = Field(default=60, ge=15, le=180)
    narration: str = Field(min_length=1, max_length=12000)
    shots: list[Shot] = Field(min_length=1, max_length=30)
    warnings: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_timeline(self) -> StoryPlan:
        previous_end = 0.0
        for shot in self.shots:
            if shot.start_seconds + 0.001 < previous_end:
                raise ValueError("shots must have a non-overlapping, increasing timeline")
            if abs(shot.start_seconds - previous_end) > 0.5:
                raise ValueError("shots must form a contiguous timeline")
            previous_end = shot.start_seconds + shot.duration_seconds
        if abs(previous_end - self.target_duration_seconds) > 0.5:
            raise ValueError("shots must cover target_duration_seconds")
        return self


class CreateJobRequest(StrictModel):
    topic: str = Field(min_length=1, max_length=500)
    source_markdown: str = Field(default="", max_length=30000)
    source_url: str | None = Field(default=None, max_length=2000)
    duration_seconds: int = Field(default=60, ge=15, le=180)
    language: str = Field(default="zh-CN", min_length=2, max_length=20)
    voice: str = Field(default="neutral", min_length=1, max_length=100)
    template_id: str = Field(default="tech-blog-v1", min_length=1, max_length=100)
    brand_preset_id: str | None = Field(default=None, max_length=100)
    character_id: UUID | None = None
    use_ai: bool = True


AssetKind = Literal["image", "audio", "font", "logo", "music", "overlay", "video", "other"]


class CreateAssetRequest(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    kind: AssetKind
    storage_key: str | None = Field(default=None, max_length=300)
    mime_type: str = Field(default="application/octet-stream", max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("storage_key")
    @classmethod
    def validate_storage_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.replace("\\", "/").strip()
        path = PurePosixPath(normalized)
        if not normalized or path.is_absolute() or ".." in path.parts:
            raise ValueError("storage_key must be a relative path without parent traversal")
        return normalized


class AssetRecord(CreateAssetRequest):
    asset_id: UUID = Field(default_factory=uuid4)
    size_bytes: int = Field(default=0, ge=0)
    sha256: str | None = Field(default=None, max_length=64)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CreateCharacterRequest(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    prompt: str = Field(min_length=1, max_length=2000)
    voice: str = Field(default="neutral", min_length=1, max_length=100)
    language: str = Field(default="zh-CN", min_length=2, max_length=20)
    reference_asset_ids: list[UUID] = Field(default_factory=list, max_length=12)


class CharacterRecord(CreateCharacterRequest):
    character_id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TemplateSummary(StrictModel):
    template_id: str = Field(min_length=1, max_length=100)
    version: int = Field(default=1, ge=1, le=100)
    brand_preset_id: str = Field(default="aivs-default-v1", min_length=1, max_length=100)
    title_style: str = Field(default="", max_length=200)
    target_duration_seconds: int = Field(ge=15, le=180)
    language: str = Field(min_length=2, max_length=20)
    voice: str = Field(min_length=1, max_length=100)
    requires_human_approval_before_publish: bool = True
    allow_external_posting: bool = False


class BrandPresetSummary(StrictModel):
    brand_preset_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    version: int = Field(default=1, ge=1, le=100)
    description: str = Field(default="", max_length=500)
    base_prompt: str = Field(default="", max_length=1000)
    camera_prompt: str = Field(default="", max_length=500)
    lighting_prompt: str = Field(default="", max_length=500)
    negative_prompt: str = Field(default="", max_length=1000)
    logo_asset_id: UUID | None = None
    intro_asset_id: UUID | None = None
    outro_asset_id: UUID | None = None


ProgressStage = Literal[
    "queued",
    "planning",
    "narration",
    "video",
    "composition",
    "social_drafts",
    "completed",
    "failed",
]


def progress_percent(
    stage: ProgressStage,
    *,
    completed_shots: int = 0,
    total_shots: int = 0,
    previous_percent: int = 0,
) -> int:
    """Map pipeline stages to a conservative operator-facing percentage."""

    if stage == "queued":
        return 0
    if stage == "planning":
        return 10
    if stage == "narration":
        return 25
    if stage == "video":
        if total_shots <= 0:
            return 30
        return min(85, 30 + round(55 * completed_shots / total_shots))
    if stage == "composition":
        return 90
    if stage == "social_drafts":
        return 95
    if stage == "completed":
        return 100
    return min(max(previous_percent, 0), 99)


class JobProgress(StrictModel):
    stage: ProgressStage = "queued"
    percent: int = Field(default=0, ge=0, le=100)
    completed_shots: int = Field(default=0, ge=0, le=30)
    total_shots: int = Field(default=0, ge=0, le=30)
    current_shot: int = Field(default=0, ge=0, le=30)
    message: str = Field(default="", max_length=300)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_shot_counts(self) -> JobProgress:
        if self.completed_shots > self.total_shots:
            raise ValueError("completed_shots cannot exceed total_shots")
        if self.current_shot > self.total_shots:
            raise ValueError("current_shot cannot exceed total_shots")
        return self


class JobRecord(StrictModel):
    job_id: UUID = Field(default_factory=uuid4)
    status: Literal["queued", "running", "succeeded", "failed"] = "queued"
    request: CreateJobRequest
    attempt: int = Field(default=0, ge=0, le=100)
    max_attempts: int = Field(default=3, ge=1, le=100)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    next_retry_at: datetime | None = None
    lease_expires_at: datetime | None = None
    plan_path: str | None = None
    subtitle_path: str | None = None
    audio_path: str | None = None
    video_path: str | None = None
    social_drafts_path: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    progress: JobProgress = Field(default_factory=JobProgress)

    @field_validator("error_message")
    @classmethod
    def limit_error_message(cls, value: str | None) -> str | None:
        if value is not None and len(value) > 500:
            return value[:500]
        return value


class JobEvent(StrictModel):
    event_id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    event_type: Literal["queued", "running", "retrying", "succeeded", "failed", "progress"]
    attempt: int = Field(default=0, ge=0, le=100)
    message: str = Field(default="", max_length=300)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class JobStatsResponse(StrictModel):
    queued: int = Field(default=0, ge=0)
    running: int = Field(default=0, ge=0)
    succeeded: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    queue_depth: int = Field(default=0, ge=0)


class ProviderStatus(StrictModel):
    provider_id: str = Field(min_length=1, max_length=100)
    kind: Literal["llm", "tts", "video"]
    capabilities: list[str] = Field(default_factory=list, max_length=20)
    configured: bool = True


class ProviderListResponse(StrictModel):
    providers: list[ProviderStatus] = Field(default_factory=list, max_length=100)


class UsageRecord(StrictModel):
    usage_id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    stage: Literal["pipeline"] = "pipeline"
    provider_id: str = Field(min_length=1, max_length=100)
    status: Literal["succeeded", "failed"]
    units: float = Field(default=1, ge=0)
    duration_seconds: int = Field(default=0, ge=0, le=3600)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class UsageSummary(StrictModel):
    total_jobs: int = Field(default=0, ge=0)
    successful_jobs: int = Field(default=0, ge=0)
    failed_jobs: int = Field(default=0, ge=0)
    total_duration_seconds: int = Field(default=0, ge=0)
    by_provider: dict[str, int] = Field(default_factory=dict)


SocialPlatform = Literal[
    "blog",
    "wechat",
    "zhihu",
    "bilibili",
    "xiaohongshu",
    "douyin",
    "podcast",
]


class PublisherStatus(StrictModel):
    publisher_id: str = Field(min_length=1, max_length=100)
    platform: SocialPlatform
    configured: bool = True


class PublisherListResponse(StrictModel):
    publishers: list[PublisherStatus] = Field(default_factory=list, max_length=100)


class SocialDraft(StrictModel):
    platform: SocialPlatform
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20_000)
    hashtags: list[str] = Field(default_factory=list, max_length=20)
    requires_human_approval: bool = True
    published: bool = False


class SocialDraftBundle(StrictModel):
    schema_version: Literal["social-drafts-v1"] = "social-drafts-v1"
    plan_id: UUID
    drafts: list[SocialDraft] = Field(min_length=1, max_length=20)


ApprovalDecision = Literal["approved", "rejected"]


class SocialApprovalRequest(StrictModel):
    platform: SocialPlatform
    decision: ApprovalDecision
    reviewer: str = Field(default="operator", min_length=1, max_length=100)
    note: str = Field(default="", max_length=2000)


class SocialApprovalRecord(SocialApprovalRequest):
    approval_id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PublishSocialDraftRequest(StrictModel):
    """Request a preview or a gated external publish attempt."""

    platform: SocialPlatform
    dry_run: bool = True
    actor: str = Field(default="agent", min_length=1, max_length=100)


PublishStatus = Literal["dry_run", "blocked", "unavailable", "published", "failed"]


class PublishSocialDraftResponse(StrictModel):
    schema_version: Literal["publish-result-v1"] = "publish-result-v1"
    job_id: UUID
    platform: SocialPlatform
    status: PublishStatus
    dry_run: bool
    approval_required: bool = True
    approved: bool = False
    publisher_id: str | None = Field(default=None, max_length=100)
    external_id: str | None = Field(default=None, max_length=300)
    audit_id: UUID
    message: str = Field(default="", max_length=500)


AuditAction = Literal[
    "publish_dry_run",
    "publish_blocked",
    "publish_unavailable",
    "publish_succeeded",
    "publish_failed",
]


class PublishAuditRecord(StrictModel):
    audit_id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    platform: SocialPlatform
    action: AuditAction
    actor: str = Field(default="agent", min_length=1, max_length=100)
    dry_run: bool
    message: str = Field(default="", max_length=500)
    external_id: str | None = Field(default=None, max_length=300)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class HealthResponse(StrictModel):
    status: Literal["ok"] = "ok"
    service: str = "ai-video-studio-api"
    version: str = "0.18.3"
