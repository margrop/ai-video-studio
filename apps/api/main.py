"""FastAPI entrypoint for queueing local render jobs."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Query, status
from fastapi.responses import FileResponse

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
    TemplateSummary,
    UsageSummary,
)
from packages.library import CatalogNotFound
from packages.runtime import AppRuntime, build_runtime
from packages.storage import FileJobStore

WEB_ROOT = Path(__file__).parents[1] / "web"


def create_app(
    *,
    store: FileJobStore | None = None,
    runtime: AppRuntime | None = None,
) -> FastAPI:
    job_store = store or FileJobStore.from_env(Path(os.getenv("AIVS_STORAGE_ROOT", ".aivs")))
    app_runtime = runtime or build_runtime(job_store.root)
    app = FastAPI(title="AI Video Studio API", version="0.2.0")

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

    @app.get("/v1/jobs/{job_id}/artifacts/{artifact_name}")
    async def get_artifact(job_id: UUID, artifact_name: str) -> FileResponse:
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
        artifact_dir = job_store.artifacts_dir / str(job_id)
        artifact_path = artifact_dir / artifact_name
        if not artifact_path.is_file():
            raise HTTPException(status_code=404, detail="artifact_not_found")
        media_type = (
            "video/mp4"
            if artifact_name.endswith(".mp4")
            else "application/json"
            if artifact_name.endswith(".json")
            else "application/octet-stream"
        )
        return FileResponse(artifact_path, media_type=media_type, filename=artifact_name)

    app.state.job_store = job_store
    app.state.runtime = app_runtime
    app.state.workflow_factory = lambda: app_runtime.workflow
    return app


app = create_app()
