"""FastAPI entrypoint for queueing local render jobs."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from packages.contracts.models import (
    AssetRecord,
    CharacterRecord,
    CreateAssetRequest,
    CreateCharacterRequest,
    CreateJobRequest,
    HealthResponse,
    JobEvent,
    JobRecord,
    JobStatsResponse,
    ProviderListResponse,
    ProviderStatus,
    PublishAuditRecord,
    PublisherListResponse,
    PublisherStatus,
    PublishSocialDraftRequest,
    PublishSocialDraftResponse,
    SocialApprovalRecord,
    SocialApprovalRequest,
    SocialDraftBundle,
    TemplateSummary,
    UsageSummary,
)
from packages.library import CatalogNotFound
from packages.publishing import (
    ApprovalStore,
    AuditStore,
    PublishingService,
    build_approval_store,
    build_audit_store,
    external_publishing_enabled,
)
from packages.runtime import AppRuntime, build_runtime
from packages.security import APIAuthenticator, build_rate_limiter, security_headers
from packages.storage import (
    ArtifactNotFound,
    ArtifactStore,
    ArtifactStoreError,
    JobStore,
    build_artifact_store,
    build_job_store,
)

WEB_ROOT = Path(__file__).parents[1] / "web"


def create_app(
    *,
    store: JobStore | None = None,
    runtime: AppRuntime | None = None,
    artifact_store: ArtifactStore | None = None,
    approval_store: ApprovalStore | None = None,
    audit_store: AuditStore | None = None,
) -> FastAPI:
    job_store = store or build_job_store(Path(os.getenv("AIVS_STORAGE_ROOT", ".aivs")))
    app_runtime = runtime or build_runtime(job_store.root)
    generated_artifacts = artifact_store or build_artifact_store(job_store.root)
    app = FastAPI(title="AI Video Studio API", version="0.11.0")
    approval_store = approval_store or build_approval_store(job_store.root / "approvals")
    audit_store = audit_store or build_audit_store(job_store.root / "publish-audit")
    publishing_service = PublishingService(
        approvals=approval_store,
        audit=audit_store,
        publishers=app_runtime.publishers,
        enabled=external_publishing_enabled(),
    )
    authenticator = APIAuthenticator.from_env()
    rate_limiter = build_rate_limiter(job_store)

    @app.middleware("http")
    async def protect_api(request: Request, call_next):
        if not request.url.path.startswith("/v1"):
            return await call_next(request)
        if not authenticator.allows(
            authorization=request.headers.get("Authorization"),
            api_key_header=request.headers.get("X-AIVS-API-Key"),
        ):
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "invalid_api_key"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        client_host = request.client.host if request.client is not None else "unknown"
        decision = rate_limiter.check(client_host)
        headers = security_headers(decision)
        if not decision.allowed:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "rate_limit_exceeded"},
                headers=headers,
            )
        response = await call_next(request)
        response.headers.update(headers)
        return response

    @app.get("/", include_in_schema=False)
    @app.get("/dashboard", include_in_schema=False)
    async def dashboard() -> FileResponse:
        return FileResponse(WEB_ROOT / "index.html", media_type="text/html")

    @app.get("/dashboard/{asset_name}", include_in_schema=False)
    async def dashboard_asset(asset_name: str) -> FileResponse:
        assets = {
            "app.js": ("application/javascript", WEB_ROOT / "app.js"),
            "styles.css": ("text/css", WEB_ROOT / "styles.css"),
        }
        if asset_name not in assets:
            raise HTTPException(status_code=404, detail="dashboard_asset_not_found")
        media_type, path = assets[asset_name]
        return FileResponse(path, media_type=media_type)

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse()

    @app.post("/v1/jobs", response_model=JobRecord, status_code=status.HTTP_202_ACCEPTED)
    async def create_job(
        request: CreateJobRequest,
        idempotency_key: Annotated[
            str | None,
            Header(alias="Idempotency-Key", max_length=200),
        ] = None,
    ) -> JobRecord:
        try:
            app_runtime.templates.get(request.template_id)
            if (
                request.character_id is not None
                and app_runtime.characters.get(request.character_id) is None
            ):
                raise CatalogNotFound(f"character is not registered: {request.character_id}")
        except CatalogNotFound as exc:
            raise HTTPException(status_code=422, detail="invalid_job_reference") from exc
        return job_store.create(request, idempotency_key=idempotency_key)

    @app.get("/v1/jobs", response_model=list[JobRecord])
    async def list_jobs(
        job_status: str | None = Query(default=None, alias="status"),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> list[JobRecord]:
        allowed_statuses = {"queued", "running", "succeeded", "failed"}
        if job_status is not None and job_status not in allowed_statuses:
            raise HTTPException(status_code=422, detail="invalid_job_status")
        return job_store.list_jobs(status=job_status, limit=limit)

    @app.get("/v1/jobs/{job_id}", response_model=JobRecord)
    async def get_job(job_id: UUID) -> JobRecord:
        record = job_store.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="job_not_found")
        return record

    @app.get("/v1/jobs/{job_id}/events", response_model=list[JobEvent])
    async def get_job_events(job_id: UUID) -> list[JobEvent]:
        if job_store.get(job_id) is None:
            raise HTTPException(status_code=404, detail="job_not_found")
        return job_store.events(job_id)

    @app.get("/v1/stats", response_model=JobStatsResponse)
    async def get_stats() -> JobStatsResponse:
        return JobStatsResponse(**job_store.stats())

    @app.get("/v1/usage", response_model=UsageSummary)
    async def get_usage() -> UsageSummary:
        return job_store.usage.summary()

    @app.get("/v1/providers", response_model=ProviderListResponse)
    async def get_providers() -> ProviderListResponse:
        return ProviderListResponse(
            providers=[
                ProviderStatus(
                    provider_id=descriptor.provider_id,
                    kind=descriptor.kind,  # type: ignore[arg-type]
                    capabilities=list(descriptor.capabilities),
                    configured=descriptor.configured,
                )
                for descriptor in app_runtime.providers.descriptors()
            ]
        )

    @app.get("/v1/publishers", response_model=PublisherListResponse)
    async def get_publishers() -> PublisherListResponse:
        return PublisherListResponse(
            publishers=[
                PublisherStatus(
                    publisher_id=descriptor.publisher_id,
                    platform=descriptor.platform,
                    configured=descriptor.configured,
                )
                for descriptor in app_runtime.publishers.descriptors()
            ]
        )

    @app.get("/v1/templates", response_model=list[TemplateSummary])
    async def get_templates() -> list[TemplateSummary]:
        return app_runtime.templates.list()

    @app.get("/v1/assets", response_model=list[AssetRecord])
    async def get_assets(limit: int = Query(default=100, ge=1, le=200)) -> list[AssetRecord]:
        return app_runtime.assets.list(limit=limit)

    @app.post("/v1/assets", response_model=AssetRecord, status_code=status.HTTP_201_CREATED)
    async def create_asset(request: CreateAssetRequest) -> AssetRecord:
        return app_runtime.assets.create(request)

    @app.get("/v1/assets/{asset_id}", response_model=AssetRecord)
    async def get_asset(asset_id: UUID) -> AssetRecord:
        record = app_runtime.assets.get(asset_id)
        if record is None:
            raise HTTPException(status_code=404, detail="asset_not_found")
        return record

    @app.get("/v1/characters", response_model=list[CharacterRecord])
    async def get_characters(
        limit: int = Query(default=100, ge=1, le=200),
    ) -> list[CharacterRecord]:
        return app_runtime.characters.list(limit=limit)

    @app.post("/v1/characters", response_model=CharacterRecord, status_code=status.HTTP_201_CREATED)
    async def create_character(request: CreateCharacterRequest) -> CharacterRecord:
        try:
            return app_runtime.characters.create(request)
        except CatalogNotFound as exc:
            raise HTTPException(status_code=422, detail="invalid_reference_asset") from exc

    @app.get("/v1/characters/{character_id}", response_model=CharacterRecord)
    async def get_character(character_id: UUID) -> CharacterRecord:
        record = app_runtime.characters.get(character_id)
        if record is None:
            raise HTTPException(status_code=404, detail="character_not_found")
        return record

    def _social_drafts(job_id: UUID) -> SocialDraftBundle:
        record = job_store.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="job_not_found")
        if record.status != "succeeded":
            raise HTTPException(status_code=409, detail="job_not_ready")
        try:
            content = generated_artifacts.read_bytes(job_id, "social-drafts.json")
        except ArtifactNotFound as exc:
            raise HTTPException(status_code=404, detail="social_drafts_not_found") from exc
        except ArtifactStoreError as exc:
            raise HTTPException(status_code=503, detail="social_drafts_unavailable") from exc
        try:
            return SocialDraftBundle.model_validate_json(content)
        except ValueError as exc:
            raise HTTPException(status_code=500, detail="social_drafts_invalid") from exc

    @app.get("/v1/jobs/{job_id}/social-drafts", response_model=SocialDraftBundle)
    async def get_social_drafts(job_id: UUID) -> SocialDraftBundle:
        return _social_drafts(job_id)

    @app.get("/v1/jobs/{job_id}/approvals", response_model=list[SocialApprovalRecord])
    async def get_approvals(job_id: UUID) -> list[SocialApprovalRecord]:
        if job_store.get(job_id) is None:
            raise HTTPException(status_code=404, detail="job_not_found")
        return approval_store.list(job_id)

    @app.post(
        "/v1/jobs/{job_id}/approvals",
        response_model=SocialApprovalRecord,
        status_code=status.HTTP_201_CREATED,
    )
    async def decide_approval(
        job_id: UUID,
        request: SocialApprovalRequest,
    ) -> SocialApprovalRecord:
        bundle = _social_drafts(job_id)
        if request.platform not in {draft.platform for draft in bundle.drafts}:
            raise HTTPException(status_code=422, detail="platform_not_in_social_drafts")
        return approval_store.decide(job_id, request)

    @app.get("/v1/jobs/{job_id}/publish-audit", response_model=list[PublishAuditRecord])
    async def get_publish_audit(job_id: UUID) -> list[PublishAuditRecord]:
        if job_store.get(job_id) is None:
            raise HTTPException(status_code=404, detail="job_not_found")
        return audit_store.list(job_id)

    @app.post(
        "/v1/jobs/{job_id}/publish",
        response_model=PublishSocialDraftResponse,
    )
    async def publish_social_draft(
        job_id: UUID,
        request: PublishSocialDraftRequest,
    ) -> PublishSocialDraftResponse:
        bundle = _social_drafts(job_id)
        draft = next((item for item in bundle.drafts if item.platform == request.platform), None)
        if draft is None:
            raise HTTPException(status_code=422, detail="platform_not_in_social_drafts")
        video_path = generated_artifacts.local_path(job_id, "video.mp4")
        return await publishing_service.publish(
            job_id=job_id,
            draft=draft,
            actor=request.actor,
            dry_run=request.dry_run,
            video_path=video_path,
        )

    @app.get("/v1/jobs/{job_id}/artifacts/{artifact_name}")
    async def get_artifact(job_id: UUID, artifact_name: str) -> Response:
        record = job_store.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="job_not_found")
        if record.status != "succeeded":
            raise HTTPException(status_code=409, detail="job_not_ready")
        allowed = {
            "video.mp4": "video_path",
            "story-plan.json": "plan_path",
            "subtitles.srt": "subtitle_path",
            "narration.wav": "audio_path",
            "social-drafts.json": "social_drafts_path",
        }
        if artifact_name not in allowed:
            raise HTTPException(status_code=404, detail="artifact_not_found")
        media_type = (
            "video/mp4"
            if artifact_name.endswith(".mp4")
            else "application/json"
            if artifact_name.endswith(".json")
            else "application/octet-stream"
        )
        try:
            local_path = generated_artifacts.local_path(job_id, artifact_name)
            if local_path is not None and local_path.is_file():
                return FileResponse(local_path, media_type=media_type, filename=artifact_name)
            if not generated_artifacts.exists(job_id, artifact_name):
                raise HTTPException(status_code=404, detail="artifact_not_found")
            return StreamingResponse(
                generated_artifacts.iter_bytes(job_id, artifact_name),
                media_type=media_type,
                headers={
                    "Content-Disposition": f'attachment; filename="{artifact_name}"',
                },
            )
        except HTTPException:
            raise
        except ArtifactNotFound as exc:
            raise HTTPException(status_code=404, detail="artifact_not_found") from exc
        except (ArtifactStoreError, ValueError) as exc:
            raise HTTPException(status_code=503, detail="artifact_unavailable") from exc

    app.state.job_store = job_store
    app.state.artifact_store = generated_artifacts
    app.state.runtime = app_runtime
    app.state.approvals = approval_store
    app.state.audit = audit_store
    app.state.publishing = publishing_service
    app.state.workflow_factory = lambda: app_runtime.workflow
    return app


app = create_app()
