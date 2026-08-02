"""Redis-backed job storage for multi-process API and worker deployments.

The backend stores metadata and queue state in Redis while reusable local
catalogs and worker staging remain below ``root``. Generated artifacts can be
published independently through the ``ArtifactStore`` S3/MinIO backend.

The implementation deliberately uses the small synchronous Redis client
surface. API callers remain async at the HTTP boundary, and workers already
perform blocking FFmpeg/provider work; keeping storage synchronous preserves
the same contract as ``FileJobStore`` and makes the backend easy to test with
an in-memory Redis-compatible fake.
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from packages.contracts.models import (
    CreateJobRequest,
    JobEvent,
    JobProgress,
    JobRecord,
    ProgressStage,
    UsageRecord,
    UsageSummary,
    progress_percent,
)

_SECRET_RE = re.compile(
    r"(?i)\b(authorization|api[_-]?key|token|password|secret)\b\s*[:=]\s*[^\s,;]+"
)


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if minimum <= value <= maximum else default


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if minimum <= value <= maximum else default


class RedisUsageLedger:
    """Idempotent terminal usage records stored under a Redis key prefix."""

    def __init__(self, client: Any, prefix: str) -> None:
        self.client = client
        self.prefix = prefix

    def _key(self, job_id: UUID) -> str:
        return f"{self.prefix}{job_id}"

    def record(
        self,
        *,
        job_id: UUID,
        provider_id: str,
        status: str,
        duration_seconds: int,
    ) -> UsageRecord:
        existing = self.client.get(self._key(job_id))
        if existing is not None:
            return UsageRecord.model_validate_json(_text(existing))

        record = UsageRecord(
            job_id=job_id,
            provider_id=provider_id,
            status=status,  # type: ignore[arg-type] - validated by UsageRecord
            duration_seconds=duration_seconds,
        )
        if self.client.set(self._key(job_id), record.model_dump_json(), nx=True):
            return record
        stored = self.client.get(self._key(job_id))
        if stored is None:
            raise RuntimeError("Redis usage record disappeared during write")
        return UsageRecord.model_validate_json(_text(stored))

    def list(self) -> list[UsageRecord]:
        records: list[UsageRecord] = []
        for key in self.client.scan_iter(match=f"{self.prefix}*"):
            value = self.client.get(_text(key))
            if value is None:
                continue
            try:
                records.append(UsageRecord.model_validate_json(_text(value)))
            except ValueError:
                continue
        return records

    def summary(self) -> UsageSummary:
        records = self.list()
        by_provider: dict[str, int] = {}
        for record in records:
            by_provider[record.provider_id] = by_provider.get(record.provider_id, 0) + 1
        return UsageSummary(
            total_jobs=len(records),
            successful_jobs=sum(record.status == "succeeded" for record in records),
            failed_jobs=sum(record.status == "failed" for record in records),
            total_duration_seconds=sum(record.duration_seconds for record in records),
            by_provider=dict(sorted(by_provider.items())),
        )


class RedisJobStore:
    """A recoverable Redis queue with idempotency and lease-based workers."""

    def __init__(
        self,
        client: Any,
        root: Path,
        *,
        namespace: str = "aivs",
        max_attempts: int = 3,
        lease_seconds: int = 300,
        retry_backoff_seconds: float = 5.0,
    ) -> None:
        if not 1 <= max_attempts <= 100:
            raise ValueError("max_attempts must be between 1 and 100")
        if not 5 <= lease_seconds <= 86_400:
            raise ValueError("lease_seconds must be between 5 and 86400")
        if not 0 <= retry_backoff_seconds <= 3_600:
            raise ValueError("retry_backoff_seconds must be between 0 and 3600")
        normalized_namespace = namespace.strip()
        if not normalized_namespace or not re.fullmatch(
            r"[A-Za-z0-9:_-]{1,80}", normalized_namespace
        ):
            raise ValueError("namespace must contain only letters, numbers, ':', '_' or '-'")

        self.client = client
        self.root = root
        self.namespace = normalized_namespace
        self.max_attempts = max_attempts
        self.lease_seconds = lease_seconds
        self.retry_backoff_seconds = retry_backoff_seconds
        self.artifacts_dir = root / "artifacts"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

        prefix = f"{self.namespace}:"
        self.jobs_prefix = f"{prefix}job:"
        self.events_prefix = f"{prefix}events:"
        self.usage_prefix = f"{prefix}usage:"
        self.idempotency_prefix = f"{prefix}idempotency:"
        self.queue_key = f"{prefix}queue"
        # The processing list is the reliable-queue handoff. A job stays in
        # it until finish/fail, so a process dying after claim is recoverable.
        self.processing_key = f"{prefix}processing"
        self.retry_key = f"{prefix}retry"
        self.recovery_lock_prefix = f"{prefix}recovery-lock:"
        self.usage = RedisUsageLedger(client, self.usage_prefix)

    @classmethod
    def from_env(cls, root: Path | None = None) -> RedisJobStore:
        """Construct a store without connecting until the first Redis call."""

        try:
            import redis
        except ImportError as exc:  # pragma: no cover - exercised in deployment
            raise RuntimeError(
                "Redis backend requires the optional dependency: pip install '.[redis]'"
            ) from exc

        redis_url = os.getenv("AIVS_REDIS_URL", "redis://127.0.0.1:6379/0")
        client = redis.Redis.from_url(redis_url, decode_responses=True)
        storage_root = root or Path(os.getenv("AIVS_STORAGE_ROOT", ".aivs"))
        return cls(
            client,
            storage_root,
            namespace=os.getenv("AIVS_REDIS_NAMESPACE", "aivs"),
            max_attempts=_env_int("AIVS_JOB_MAX_ATTEMPTS", 3, 1, 100),
            lease_seconds=_env_int("AIVS_JOB_LEASE_SECONDS", 300, 5, 86_400),
            retry_backoff_seconds=_env_float("AIVS_JOB_RETRY_BACKOFF_SECONDS", 5.0, 0, 3_600),
        )

    @staticmethod
    def _safe_message(message: str) -> str:
        sanitized = _SECRET_RE.sub(r"\1=[REDACTED]", message.replace("\n", " "))
        return sanitized[:500]

    @staticmethod
    def _fingerprint(value: str) -> str:
        return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()

    def _job_key(self, job_id: UUID) -> str:
        return f"{self.jobs_prefix}{job_id}"

    def _event_key(self, job_id: UUID) -> str:
        return f"{self.events_prefix}{job_id}"

    def _idempotency_key(self, key: str) -> str:
        return f"{self.idempotency_prefix}{self._fingerprint(key)}"

    def _append_event(self, record: JobRecord, event_type: str, message: str) -> None:
        event = JobEvent(
            job_id=record.job_id,
            event_type=event_type,  # type: ignore[arg-type] - validated by JobEvent
            attempt=record.attempt,
            message=self._safe_message(message),
        )
        self.client.rpush(self._event_key(record.job_id), event.model_dump_json())

    def _enqueue(self, record: JobRecord) -> None:
        self.client.rpush(self.queue_key, str(record.job_id))

    def _remove_processing(self, job_id: UUID) -> None:
        self.client.lrem(self.processing_key, 0, str(job_id))

    def _read_idempotent_record(self, idempotency_key: str) -> JobRecord | None:
        raw_job_id = self.client.get(self._idempotency_key(idempotency_key))
        if raw_job_id is None:
            return None
        try:
            job_id = UUID(_text(raw_job_id))
        except ValueError:
            return None
        record = self.get(job_id)
        if record is not None and record.status == "queued":
            job_id_text = str(job_id)
            queue_ids = {_text(value) for value in self.client.lrange(self.queue_key, 0, -1)}
            processing_ids = set(self._processing_ids())
            retry_ids = {_text(value) for value in self.client.zrange(self.retry_key, 0, -1)}
            if (
                job_id_text not in queue_ids
                and job_id_text not in processing_ids
                and job_id_text not in retry_ids
            ):
                self._enqueue(record)
        return record

    def create(
        self,
        request: CreateJobRequest,
        *,
        idempotency_key: str | None = None,
    ) -> JobRecord:
        normalized_key = (idempotency_key or "").strip()
        if normalized_key:
            existing = self._read_idempotent_record(normalized_key)
            if existing is not None:
                return existing

        record = JobRecord(request=request, max_attempts=self.max_attempts)
        self.save(record)
        if normalized_key:
            index_key = self._idempotency_key(normalized_key)
            if not self.client.set(index_key, str(record.job_id), nx=True):
                existing = self._read_idempotent_record(normalized_key)
                self.client.delete(self._job_key(record.job_id))
                if existing is not None:
                    return existing
                raise RuntimeError("Redis idempotency index is unavailable")
        self._enqueue(record)
        self._append_event(record, "queued", "job accepted")
        return record

    def get(self, job_id: UUID) -> JobRecord | None:
        raw = self.client.get(self._job_key(job_id))
        if raw is None:
            return None
        return JobRecord.model_validate_json(_text(raw))

    def save(self, record: JobRecord) -> JobRecord:
        record.updated_at = datetime.now(UTC)
        self.client.set(self._job_key(record.job_id), record.model_dump_json())
        return record

    def update_progress(
        self,
        record: JobRecord,
        *,
        stage: ProgressStage,
        completed_shots: int = 0,
        total_shots: int = 0,
        current_shot: int = 0,
        message: str = "",
    ) -> JobRecord:
        record.progress = JobProgress(
            stage=stage,
            percent=progress_percent(
                stage,
                completed_shots=completed_shots,
                total_shots=total_shots,
                previous_percent=record.progress.percent,
            ),
            completed_shots=completed_shots,
            total_shots=total_shots,
            current_shot=current_shot,
            message=self._safe_message(message),
        )
        self.save(record)
        self._append_event(record, "progress", record.progress.message)
        return record

    def _processing_ids(self) -> list[str]:
        return [_text(value) for value in self.client.lrange(self.processing_key, 0, -1)]

    def _promote_retries(self, now: datetime) -> None:
        ready = self.client.zrangebyscore(self.retry_key, "-inf", now.timestamp())
        for raw_job_id in ready:
            job_id_text = _text(raw_job_id)
            if not self.client.zrem(self.retry_key, job_id_text):
                continue
            try:
                record = self.get(UUID(job_id_text))
            except ValueError:
                record = None
            if record is None or record.status != "queued":
                continue
            if record.next_retry_at is not None and record.next_retry_at > now:
                self.client.zadd(self.retry_key, {job_id_text: record.next_retry_at.timestamp()})
                continue
            self._enqueue(record)

    def recover_expired_leases(self) -> int:
        """Requeue or fail jobs left in the processing list after a crash."""

        now = datetime.now(UTC)
        recovered = 0
        for job_id_text in dict.fromkeys(self._processing_ids()):
            lock_key = f"{self.recovery_lock_prefix}{job_id_text}"
            if not self.client.set(lock_key, "1", nx=True, ex=5):
                continue
            try:
                job_id = UUID(job_id_text)
            except ValueError:
                self._remove_processing_text(job_id_text)
                self.client.delete(lock_key)
                continue
            try:
                record = self.get(job_id)
                if record is None:
                    self._remove_processing(job_id)
                    continue
                if record.status != "running":
                    self._remove_processing(job_id)
                    if record.status == "queued":
                        self._enqueue(record)
                    continue
                if record.lease_expires_at is None or record.lease_expires_at > now:
                    continue

                recovered += 1
                self._remove_processing(job_id)
                if record.attempt < record.max_attempts:
                    record.status = "queued"
                    record.next_retry_at = now
                    record.lease_expires_at = None
                    record.error_code = "lease_expired"
                    record.error_message = "worker lease expired; job requeued"
                    self.save(record)
                    self._enqueue(record)
                    self._append_event(record, "retrying", "worker lease expired; job requeued")
                else:
                    record.status = "failed"
                    record.lease_expires_at = None
                    record.error_code = "lease_expired"
                    record.error_message = "worker lease expired; retry budget exhausted"
                    self.save(record)
                    self._append_event(record, "failed", record.error_message)
                    self.usage.record(
                        job_id=record.job_id,
                        provider_id="pipeline",
                        status="failed",
                        duration_seconds=record.request.duration_seconds,
                    )
            finally:
                self.client.delete(lock_key)
        return recovered

    def _remove_processing_text(self, job_id: str) -> None:
        self.client.lrem(self.processing_key, 0, job_id)

    def claim_next(self) -> JobRecord | None:
        self.recover_expired_leases()
        now = datetime.now(UTC)
        self._promote_retries(now)
        while True:
            raw_job_id = self.client.rpoplpush(self.queue_key, self.processing_key)
            if raw_job_id is None:
                return None
            job_id_text = _text(raw_job_id)
            try:
                job_id = UUID(job_id_text)
            except ValueError:
                self._remove_processing_text(job_id_text)
                continue
            record = self.get(job_id)
            if record is None:
                self._remove_processing(job_id)
                continue
            if record.status != "queued":
                self._remove_processing(job_id)
                continue
            if record.next_retry_at is not None and record.next_retry_at > now:
                self._remove_processing(job_id)
                self.client.zadd(self.retry_key, {job_id_text: record.next_retry_at.timestamp()})
                continue

            record.status = "running"
            record.attempt += 1
            record.next_retry_at = None
            record.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            record.error_code = None
            record.error_message = None
            record.progress = JobProgress(
                stage="planning", percent=10, message="worker claimed job"
            )
            self.save(record)
            self._append_event(record, "running", "worker claimed job")
            return record

    def finish(self, record: JobRecord, *, provider_id: str = "offline-renderer") -> JobRecord:
        record.lease_expires_at = None
        record.next_retry_at = None
        total_shots = record.progress.total_shots
        record.progress = JobProgress(
            stage="completed",
            percent=100,
            completed_shots=total_shots,
            total_shots=total_shots,
            current_shot=total_shots,
            message="render completed",
        )
        self.save(record)
        self._remove_processing(record.job_id)
        if record.status == "succeeded":
            self._append_event(record, "succeeded", "render completed")
            self.usage.record(
                job_id=record.job_id,
                provider_id=provider_id,
                status="succeeded",
                duration_seconds=record.request.duration_seconds,
            )
        return record

    def fail(
        self,
        record: JobRecord,
        *,
        error_code: str,
        error_message: str,
        retryable: bool = True,
        provider_id: str = "pipeline",
    ) -> JobRecord:
        now = datetime.now(UTC)
        record.error_code = error_code[:100]
        record.error_message = self._safe_message(error_message)
        record.lease_expires_at = None
        self._remove_processing(record.job_id)
        if retryable and record.attempt < record.max_attempts:
            delay = min(
                self.retry_backoff_seconds * (2 ** max(0, record.attempt - 1)),
                3_600,
            )
            record.status = "queued"
            record.next_retry_at = now + timedelta(seconds=delay)
            record.progress = JobProgress(stage="queued", percent=0, message="retry scheduled")
            self.save(record)
            self.client.zadd(
                self.retry_key,
                {str(record.job_id): record.next_retry_at.timestamp()},
            )
            self._append_event(record, "retrying", f"{record.error_code}; retry scheduled")
            return record

        record.status = "failed"
        record.next_retry_at = None
        record.progress = JobProgress(
            stage="failed",
            percent=record.progress.percent,
            completed_shots=record.progress.completed_shots,
            total_shots=record.progress.total_shots,
            current_shot=record.progress.current_shot,
            message=record.error_message or record.error_code,
        )
        self.save(record)
        self._append_event(record, "failed", record.error_message or record.error_code)
        self.usage.record(
            job_id=record.job_id,
            provider_id=provider_id,
            status="failed",
            duration_seconds=record.request.duration_seconds,
        )
        return record

    def list_jobs(self, *, status: str | None = None, limit: int = 50) -> list[JobRecord]:
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        records: list[JobRecord] = []
        for raw_key in self.client.scan_iter(match=f"{self.jobs_prefix}*"):
            raw = self.client.get(_text(raw_key))
            if raw is None:
                continue
            try:
                record = JobRecord.model_validate_json(_text(raw))
            except ValueError:
                continue
            if status is None or record.status == status:
                records.append(record)
        records.sort(key=lambda item: item.created_at, reverse=True)
        return records[:limit]

    def events(self, job_id: UUID) -> list[JobEvent]:
        events: list[JobEvent] = []
        for raw in self.client.lrange(self._event_key(job_id), 0, -1):
            try:
                events.append(JobEvent.model_validate_json(_text(raw)))
            except ValueError:
                continue
        return events

    def stats(self) -> dict[str, int]:
        counts = {"queued": 0, "running": 0, "succeeded": 0, "failed": 0}
        for raw_key in self.client.scan_iter(match=f"{self.jobs_prefix}*"):
            raw = self.client.get(_text(raw_key))
            if raw is None:
                continue
            try:
                record = JobRecord.model_validate_json(_text(raw))
            except ValueError:
                continue
            counts[record.status] += 1
        counts["queue_depth"] = int(self.client.llen(self.queue_key)) + int(
            self.client.zcard(self.retry_key)
        )
        return counts
