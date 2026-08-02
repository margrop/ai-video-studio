"""Durable local job storage with leases, retries and idempotency.

The filesystem backend is intentionally small, but its state transitions are
explicit so it can be replaced by Redis/Postgres without changing the API or
worker contracts. Queue markers are claimed with an atomic rename; job state
is written with an atomic replace.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from packages.contracts.models import CreateJobRequest, JobEvent, JobRecord

_SECRET_RE = re.compile(
    r"(?i)\b(authorization|api[_-]?key|token|password|secret)\b\s*[:=]\s*[^\s,;]+"
)


class FileJobStore:
    """A recoverable queue backed by a directory tree.

    ``max_attempts`` and lease settings are service-owned policy. They are not
    accepted from ``CreateJobRequest`` so article text cannot change retry or
    resource behavior.
    """

    def __init__(
        self,
        root: Path,
        *,
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

        self.root = root
        self.max_attempts = max_attempts
        self.lease_seconds = lease_seconds
        self.retry_backoff_seconds = retry_backoff_seconds
        self.jobs_dir = root / "jobs"
        self.queue_dir = root / "queue"
        self.processing_dir = root / "processing"
        self.artifacts_dir = root / "artifacts"
        self.events_dir = root / "events"
        self.idempotency_dir = root / "idempotency"
        for directory in (
            self.jobs_dir,
            self.queue_dir,
            self.processing_dir,
            self.artifacts_dir,
            self.events_dir,
            self.idempotency_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls, root: Path | None = None) -> FileJobStore:
        """Build storage from server-owned environment configuration."""

        def env_int(name: str, default: int, minimum: int, maximum: int) -> int:
            try:
                value = int(os.getenv(name, str(default)))
            except ValueError:
                return default
            return value if minimum <= value <= maximum else default

        def env_float(name: str, default: float, minimum: float, maximum: float) -> float:
            try:
                value = float(os.getenv(name, str(default)))
            except ValueError:
                return default
            return value if minimum <= value <= maximum else default

        storage_root = root or Path(os.getenv("AIVS_STORAGE_ROOT", ".aivs"))
        return cls(
            storage_root,
            max_attempts=env_int("AIVS_JOB_MAX_ATTEMPTS", 3, 1, 100),
            lease_seconds=env_int("AIVS_JOB_LEASE_SECONDS", 300, 5, 86_400),
            retry_backoff_seconds=env_float("AIVS_JOB_RETRY_BACKOFF_SECONDS", 5.0, 0, 3_600),
        )

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

    def _exclusive_write(self, path: Path, content: str) -> None:
        """Create an index entry without allowing concurrent duplicate owners."""

        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            if path.exists():
                path.unlink()
            raise

    def _job_path(self, job_id: UUID) -> Path:
        return self.jobs_dir / f"{job_id}.json"

    def _queue_path(self, job_id: UUID) -> Path:
        return self.queue_dir / f"{job_id}.json"

    def _processing_path(self, job_id: UUID) -> Path:
        return self.processing_dir / f"{job_id}.json"

    def _event_path(self, job_id: UUID) -> Path:
        return self.events_dir / f"{job_id}.jsonl"

    @staticmethod
    def _safe_message(message: str) -> str:
        sanitized = _SECRET_RE.sub(r"\1=[REDACTED]", message.replace("\n", " "))
        return sanitized[:500]

    @staticmethod
    def _fingerprint(idempotency_key: str) -> str:
        return hashlib.sha256(idempotency_key.strip().encode("utf-8")).hexdigest()

    def _idempotency_path(self, idempotency_key: str) -> Path:
        return self.idempotency_dir / f"{self._fingerprint(idempotency_key)}.json"

    def _append_event(self, record: JobRecord, event_type: str, message: str) -> None:
        event = JobEvent(
            job_id=record.job_id,
            event_type=event_type,  # type: ignore[arg-type] - validated by JobEvent
            attempt=record.attempt,
            message=self._safe_message(message),
        )
        path = self._event_path(record.job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json() + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _enqueue(self, record: JobRecord) -> None:
        self._atomic_write(self._queue_path(record.job_id), str(record.job_id))

    def _remove_processing(self, job_id: UUID) -> None:
        processing_path = self._processing_path(job_id)
        if processing_path.exists():
            processing_path.unlink()

    def _read_idempotent_record(self, idempotency_key: str) -> JobRecord | None:
        index_path = self._idempotency_path(idempotency_key)
        if not index_path.exists():
            return None
        try:
            job_id = UUID(index_path.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            index_path.unlink(missing_ok=True)
            return None
        record = self.get(job_id)
        if record is None:
            index_path.unlink(missing_ok=True)
            return None
        if record.status == "queued":
            queue_path = self._queue_path(record.job_id)
            processing_path = self._processing_path(record.job_id)
            if not queue_path.exists() and not processing_path.exists():
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
            index_path = self._idempotency_path(normalized_key)
            try:
                self._exclusive_write(index_path, str(record.job_id))
            except FileExistsError:
                existing = self._read_idempotent_record(normalized_key)
                self._job_path(record.job_id).unlink(missing_ok=True)
                if existing is not None:
                    return existing
                raise

        self._enqueue(record)
        self._append_event(record, "queued", "job accepted")
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

    def recover_expired_leases(self) -> int:
        """Requeue or fail jobs left in processing after a worker crash."""

        now = datetime.now(UTC)
        recovered = 0
        for processing_path in sorted(self.processing_dir.glob("*.json")):
            try:
                job_id = UUID(processing_path.stem)
            except ValueError:
                processing_path.unlink(missing_ok=True)
                continue
            record = self.get(job_id)
            if record is None:
                processing_path.unlink(missing_ok=True)
                continue
            if record.status != "running":
                processing_path.unlink(missing_ok=True)
                continue
            if record.lease_expires_at is None or record.lease_expires_at > now:
                continue

            recovered += 1
            if record.attempt < record.max_attempts:
                record.status = "queued"
                record.next_retry_at = now
                record.lease_expires_at = None
                record.error_code = "lease_expired"
                record.error_message = "worker lease expired; job requeued"
                self.save(record)
                processing_path.replace(self._queue_path(record.job_id))
                self._append_event(record, "retrying", "worker lease expired; job requeued")
            else:
                record.status = "failed"
                record.lease_expires_at = None
                record.error_code = "lease_expired"
                record.error_message = "worker lease expired; retry budget exhausted"
                self.save(record)
                processing_path.unlink(missing_ok=True)
                self._append_event(record, "failed", record.error_message)
        return recovered

    def claim_next(self) -> JobRecord | None:
        self.recover_expired_leases()
        now = datetime.now(UTC)
        for queued_path in sorted(self.queue_dir.glob("*.json")):
            try:
                job_id = UUID(queued_path.stem)
            except ValueError:
                queued_path.unlink(missing_ok=True)
                continue

            record = self.get(job_id)
            if record is None:
                queued_path.unlink(missing_ok=True)
                continue
            if record.status != "queued":
                queued_path.unlink(missing_ok=True)
                continue
            if record.next_retry_at is not None and record.next_retry_at > now:
                continue

            processing_path = self._processing_path(job_id)
            try:
                queued_path.replace(processing_path)
            except FileNotFoundError:
                continue

            record = self.get(job_id)
            if record is None:
                processing_path.unlink(missing_ok=True)
                continue
            record.status = "running"
            record.attempt += 1
            record.next_retry_at = None
            record.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            record.error_code = None
            record.error_message = None
            self.save(record)
            self._append_event(record, "running", "worker claimed job")
            return record
        return None

    def finish(self, record: JobRecord) -> JobRecord:
        """Persist a terminal success and remove its processing marker."""

        record.lease_expires_at = None
        record.next_retry_at = None
        self.save(record)
        self._remove_processing(record.job_id)
        if record.status == "succeeded":
            self._append_event(record, "succeeded", "render completed")
        return record

    def fail(
        self,
        record: JobRecord,
        *,
        error_code: str,
        error_message: str,
        retryable: bool = True,
    ) -> JobRecord:
        """Record a failure and schedule a bounded retry when allowed."""

        now = datetime.now(UTC)
        record.error_code = error_code[:100]
        record.error_message = self._safe_message(error_message)
        record.lease_expires_at = None
        if retryable and record.attempt < record.max_attempts:
            delay = min(
                self.retry_backoff_seconds * (2 ** max(0, record.attempt - 1)),
                3_600,
            )
            record.status = "queued"
            record.next_retry_at = now + timedelta(seconds=delay)
            self.save(record)
            self._remove_processing(record.job_id)
            self._enqueue(record)
            self._append_event(record, "retrying", f"{record.error_code}; retry scheduled")
            return record

        record.status = "failed"
        record.next_retry_at = None
        self.save(record)
        self._remove_processing(record.job_id)
        self._append_event(record, "failed", record.error_message or record.error_code)
        return record

    def list_jobs(self, *, status: str | None = None, limit: int = 50) -> list[JobRecord]:
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        records: list[JobRecord] = []
        for path in self.jobs_dir.glob("*.json"):
            try:
                record = JobRecord.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if status is None or record.status == status:
                records.append(record)
        records.sort(key=lambda item: item.created_at, reverse=True)
        return records[:limit]

    def events(self, job_id: UUID) -> list[JobEvent]:
        path = self._event_path(job_id)
        if not path.exists():
            return []
        events: list[JobEvent] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                events.append(JobEvent.model_validate_json(line))
            except ValueError:
                continue
        return events

    def stats(self) -> dict[str, int]:
        counts = {"queued": 0, "running": 0, "succeeded": 0, "failed": 0}
        for record in self.list_jobs(limit=200):
            counts[record.status] += 1
        counts["queue_depth"] = sum(1 for _ in self.queue_dir.glob("*.json"))
        return counts
