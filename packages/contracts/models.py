"""Stable, provider-neutral contracts for the first pipeline slice."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    """Reject unknown fields at every public boundary."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Shot(StrictModel):
    id: str = Field(min_length=1, max_length=64)
    start_seconds: float = Field(ge=0, le=3600)
    duration_seconds: float = Field(gt=0, le=180)
    narration: str = Field(min_length=1, max_length=2000)
    visual: str = Field(min_length=1, max_length=1000)
    camera: str = Field(default="medium shot", max_length=300)
    prompt: str = Field(default="", max_length=4000)


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
            previous_end = shot.start_seconds + shot.duration_seconds
        if previous_end > self.target_duration_seconds + 0.5:
            raise ValueError("shots exceed target_duration_seconds")
        return self


class CreateJobRequest(StrictModel):
    topic: str = Field(min_length=1, max_length=500)
    source_markdown: str = Field(default="", max_length=30000)
    duration_seconds: int = Field(default=60, ge=15, le=180)
    language: str = Field(default="zh-CN", min_length=2, max_length=20)
    voice: str = Field(default="neutral", min_length=1, max_length=100)
    use_ai: bool = True


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
    error_code: str | None = None
    error_message: str | None = None

    @field_validator("error_message")
    @classmethod
    def limit_error_message(cls, value: str | None) -> str | None:
        if value is not None and len(value) > 500:
            return value[:500]
        return value


class JobEvent(StrictModel):
    event_id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    event_type: Literal["queued", "running", "retrying", "succeeded", "failed"]
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


class HealthResponse(StrictModel):
    status: Literal["ok"] = "ok"
    service: str = "ai-video-studio-api"
    version: str = "0.2.0"
