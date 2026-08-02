"""FastAPI entrypoint for queueing local render jobs."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse

from packages.contracts.models import CreateJobRequest, HealthResponse, JobRecord
from packages.runtime import build_default_workflow
from packages.storage import FileJobStore


def create_app(*, store: FileJobStore | None = None) -> FastAPI:
    job_store = store or FileJobStore(Path(os.getenv("AIVS_STORAGE_ROOT", ".aivs")))
    app = FastAPI(title="AI Video Studio API", version="0.1.0")

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse()

    @app.post("/v1/jobs", response_model=JobRecord, status_code=status.HTTP_202_ACCEPTED)
    async def create_job(request: CreateJobRequest) -> JobRecord:
        return job_store.create(request)

    @app.get("/v1/jobs/{job_id}", response_model=JobRecord)
    async def get_job(job_id: UUID) -> JobRecord:
        record = job_store.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="job_not_found")
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
    app.state.workflow_factory = build_default_workflow
    return app


app = create_app()
