"""A Redis-free queue that can be replaced by a durable backend in Phase 2."""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from packages.contracts.models import CreateJobRequest, JobRecord


class FileJobStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.jobs_dir = root / "jobs"
        self.queue_dir = root / "queue"
        self.processing_dir = root / "processing"
        self.artifacts_dir = root / "artifacts"
        for directory in (self.jobs_dir, self.queue_dir, self.processing_dir, self.artifacts_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def _atomic_write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            Path(temp_name).replace(path)
        finally:
            temporary = Path(temp_name)
            if temporary.exists():
                temporary.unlink()

    def _job_path(self, job_id: UUID) -> Path:
        return self.jobs_dir / f"{job_id}.json"

    def create(self, request: CreateJobRequest) -> JobRecord:
        record = JobRecord(request=request)
        self.save(record)
        self._atomic_write(
            self.queue_dir / f"{record.job_id}.json",
            record.model_dump_json(indent=2),
        )
        return record

    def get(self, job_id: UUID) -> JobRecord | None:
        path = self._job_path(job_id)
        if not path.exists():
            return None
        return JobRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, record: JobRecord) -> JobRecord:
        record.updated_at = datetime.now(UTC)
        self._atomic_write(self._job_path(record.job_id), record.model_dump_json(indent=2))
        return record

    def claim_next(self) -> JobRecord | None:
        for queued_path in sorted(self.queue_dir.glob("*.json")):
            processing_path = self.processing_dir / queued_path.name
            try:
                queued_path.replace(processing_path)
            except FileNotFoundError:
                continue
            record = JobRecord.model_validate_json(processing_path.read_text(encoding="utf-8"))
            record.status = "running"
            self.save(record)
            return record
        return None

    def finish(self, record: JobRecord) -> JobRecord:
        processing_path = self.processing_dir / f"{record.job_id}.json"
        if processing_path.exists():
            processing_path.unlink()
        return self.save(record)
