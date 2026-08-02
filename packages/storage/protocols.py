"""Storage contracts shared by local and distributed backends."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol
from uuid import UUID

from packages.contracts.models import (
    CreateJobRequest,
    JobEvent,
    JobRecord,
    ProgressStage,
    UsageRecord,
    UsageSummary,
)


class UsageLedgerProtocol(Protocol):
    def record(
        self,
        *,
        job_id: UUID,
        provider_id: str,
        status: str,
        duration_seconds: int,
    ) -> UsageRecord: ...

    def summary(self) -> UsageSummary: ...


class JobStore(Protocol):
    """The queue surface consumed by the API, worker and MCP service."""

    root: Path
    artifacts_dir: Path
    usage: UsageLedgerProtocol

    def create(
        self,
        request: CreateJobRequest,
        *,
        idempotency_key: str | None = None,
    ) -> JobRecord: ...

    def get(self, job_id: UUID) -> JobRecord | None: ...

    def save(self, record: JobRecord) -> JobRecord: ...

    def update_progress(
        self,
        record: JobRecord,
        *,
        stage: ProgressStage,
        completed_shots: int = 0,
        total_shots: int = 0,
        current_shot: int = 0,
        message: str = "",
    ) -> JobRecord: ...

    def claim_next(self) -> JobRecord | None: ...

    def finish(self, record: JobRecord, *, provider_id: str = "offline-renderer") -> JobRecord: ...

    def fail(
        self,
        record: JobRecord,
        *,
        error_code: str,
        error_message: str,
        retryable: bool = True,
        provider_id: str = "pipeline",
    ) -> JobRecord: ...

    def list_jobs(self, *, status: str | None = None, limit: int = 50) -> list[JobRecord]: ...

    def events(self, job_id: UUID) -> list[JobEvent]: ...

    def stats(self) -> dict[str, int]: ...
