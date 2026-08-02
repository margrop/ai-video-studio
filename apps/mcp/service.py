"""Agent-facing service methods with the same contracts as the HTTP API."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from apps.worker.main import process_once
from packages.contracts.models import CreateJobRequest, SocialDraftBundle, StoryPlan
from packages.publishing import (
    ApprovalStore,
    AuditStore,
    PublishingService,
    build_approval_store,
    build_audit_store,
    external_publishing_enabled,
    write_social_drafts,
)
from packages.runtime import AppRuntime, build_runtime
from packages.storage import ArtifactStore, JobStore, build_artifact_store, build_job_store


@dataclass(slots=True)
class AIVSToolService:
    store: JobStore
    runtime: AppRuntime
    artifact_store: ArtifactStore | None = None
    approvals: ApprovalStore | None = None
    audit: AuditStore | None = None

    def __post_init__(self) -> None:
        if self.artifact_store is None:
            self.artifact_store = build_artifact_store(self.store.root)
        if self.approvals is None:
            self.approvals = build_approval_store(self.store.root / "approvals")
        if self.audit is None:
            self.audit = build_audit_store(self.store.root / "publish-audit")

    @classmethod
    def from_env(cls) -> AIVSToolService:
        store = build_job_store()
        return cls(
            store=store,
            runtime=build_runtime(store.root),
            approvals=build_approval_store(store.root / "approvals"),
            audit=build_audit_store(store.root / "publish-audit"),
        )

    def _artifact_paths(self, job_id: UUID) -> dict[str, str]:
        if self.artifact_store is None:  # pragma: no cover - initialized in __post_init__
            raise RuntimeError("artifact store is not configured")
        directory = self.artifact_store.job_dir(job_id)
        names = (
            "video.mp4",
            "story-plan.json",
            "subtitles.srt",
            "narration.wav",
            "social-drafts.json",
        )
        return {name: str(directory / name) for name in names if (directory / name).is_file()}

    async def generate_video(
        self,
        *,
        topic: str,
        source_markdown: str = "",
        duration_seconds: int = 60,
        language: str = "zh-CN",
        voice: str = "neutral",
        use_ai: bool = False,
        template_id: str = "tech-blog-v1",
        brand_preset_id: str | None = None,
        character_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        request = CreateJobRequest(
            topic=topic,
            source_markdown=source_markdown,
            duration_seconds=duration_seconds,
            language=language,
            voice=voice,
            use_ai=use_ai,
            template_id=template_id,
            brand_preset_id=brand_preset_id,
            character_id=UUID(character_id) if character_id else None,
        )
        record = self.store.create(request, idempotency_key=idempotency_key)
        if record.status == "queued":
            await process_once(self.store, self.runtime, self.artifact_store)
            record = self.store.get(record.job_id) or record
        return {
            "job": record.model_dump(mode="json"),
            "artifacts": self._artifact_paths(record.job_id),
        }

    def inspect_job(self, job_id: str) -> dict[str, object]:
        record = self.store.get(UUID(job_id))
        if record is None:
            raise KeyError("job_not_found")
        return {
            "job": record.model_dump(mode="json"),
            "events": [event.model_dump(mode="json") for event in self.store.events(record.job_id)],
            "artifacts": self._artifact_paths(record.job_id),
        }

    def list_jobs(self, *, status: str | None = None, limit: int = 20) -> list[dict[str, object]]:
        records = self.store.list_jobs(status=status, limit=limit)
        return [record.model_dump(mode="json") for record in records]

    def list_brand_presets(self) -> list[dict[str, object]]:
        return [
            item.model_dump(mode="json") for item in self.runtime.templates.brand_presets.list()
        ]

    def create_social_drafts(self, job_id: str) -> dict[str, object]:
        record = self.store.get(UUID(job_id))
        if record is None:
            raise KeyError("job_not_found")
        if record.status != "succeeded":
            raise ValueError("job_not_ready")
        if self.artifact_store is None:  # pragma: no cover - initialized in __post_init__
            raise RuntimeError("artifact store is not configured")
        plan = StoryPlan.model_validate_json(
            self.artifact_store.read_bytes(record.job_id, "story-plan.json")
        )
        output_dir = self.artifact_store.job_dir(record.job_id)
        path = write_social_drafts(
            plan,
            output_dir / "social-drafts.json",
        )
        self.artifact_store.publish(record.job_id, output_dir)
        record.social_drafts_path = path.name
        self.store.save(record)
        return {"job_id": str(record.job_id), "artifact": str(path)}

    async def publish_social_draft(
        self,
        *,
        job_id: str,
        platform: str,
        actor: str = "agent",
        dry_run: bool = True,
    ) -> dict[str, object]:
        record = self.store.get(UUID(job_id))
        if record is None:
            raise KeyError("job_not_found")
        if record.status != "succeeded":
            raise ValueError("job_not_ready")
        if self.artifact_store is None or self.approvals is None or self.audit is None:
            raise RuntimeError("publishing stores are not configured")
        bundle = SocialDraftBundle.model_validate_json(
            self.artifact_store.read_bytes(record.job_id, "social-drafts.json")
        )
        draft = next((item for item in bundle.drafts if item.platform == platform), None)
        if draft is None:
            raise ValueError("platform_not_in_social_drafts")
        result = await PublishingService(
            approvals=self.approvals,
            audit=self.audit,
            publishers=self.runtime.publishers,
            enabled=external_publishing_enabled(),
        ).publish(
            job_id=record.job_id,
            draft=draft,
            actor=actor,
            dry_run=dry_run,
            video_path=self.artifact_store.local_path(record.job_id, "video.mp4"),
        )
        return result.model_dump(mode="json")

    def list_publish_audit(self, job_id: str) -> list[dict[str, object]]:
        if self.audit is None:
            raise RuntimeError("audit store is not configured")
        parsed_job_id = UUID(job_id)
        if self.store.get(parsed_job_id) is None:
            raise KeyError("job_not_found")
        return [item.model_dump(mode="json") for item in self.audit.list(parsed_job_id)]
