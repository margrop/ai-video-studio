"""FastAPI entrypoint for queueing local render jobs."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Query, status
from fastapi.responses import FileResponse

from packages.contracts.models import (
    CreateJobRequest,
    HealthResponse,
    JobEvent,
    JobRecord,
    JobStatsResponse,
    ProviderListResponse,
    ProviderStatus,
)
from packages.runtime import AppRuntime, build_runtime
from packages.storage import FileJobStore


def create_app(
    *,
    store: FileJobStore | None = None,
    runtime: AppRuntime | None = None,
) -> FastAPI:
    job_store = store or FileJobStore.from_env(Path(os.getenv("AIVS_STORAGE_ROOT", ".aivs")))
    app_runtime = runtime or build_runtime()
    app = FastAPI(title="AI Video Studio API", version="0.2.0")

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
        }
        if artifact_name not in allowed:
            raise HTTPException(status_code=404, detail="artifact_not_found")
        artifact_dir = job_store.artifacts_dir / str(job_id)
        artifact_path = artifact_dir / artifact_name
        if not artifact_path.is_file():
            raise HTTPException(status_code=404, detail="artifact_not_found")
        media_type = "video/mp4" if artifact_name.endswith(".mp4") else "application/octet-stream"
        return FileResponse(artifact_path, media_type=media_type, filename=artifact_name)

    app.state.job_store = job_store
    app.state.runtime = app_runtime
    app.state.workflow_factory = lambda: app_runtime.workflow
    return app


app = create_app()
