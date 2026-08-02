"""PostgreSQL job metadata and queue storage.

The backend keeps the same synchronous ``JobStore`` contract as the local and
Redis implementations. Each operation uses a short-lived connection so the
API's synchronous storage calls do not share a psycopg connection across
requests. Generated files remain behind ``ArtifactStore``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from packages.contracts.models import (
    CreateJobRequest,
    JobEvent,
    JobRecord,
    UsageRecord,
    UsageSummary,
)

_SECRET_RE = re.compile(
    r"(?i)\b(authorization|api[_-]?key|token|password|secret)\b\s*[:=]\s*[^\s,;]+"
)
_JOB_COLUMNS = (
    "job_id",
    "status",
    "request_json",
    "attempt",
    "max_attempts",
    "created_at",
    "updated_at",
    "next_retry_at",
    "lease_expires_at",
    "plan_path",
    "subtitle_path",
    "audio_path",
    "video_path",
    "social_drafts_path",
    "error_code",
    "error_message",
)

SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS aivs_jobs (
        job_id UUID PRIMARY KEY,
        status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
        request_json JSONB NOT NULL,
        attempt INTEGER NOT NULL CHECK (attempt >= 0),
        max_attempts INTEGER NOT NULL CHECK (max_attempts BETWEEN 1 AND 100),
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL,
        next_retry_at TIMESTAMPTZ,
        lease_expires_at TIMESTAMPTZ,
        plan_path TEXT,
        subtitle_path TEXT,
        audio_path TEXT,
        video_path TEXT,
        social_drafts_path TEXT,
        error_code TEXT,
        error_message TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS aivs_jobs_status_created_idx ON aivs_jobs (status, created_at)",
    """
    CREATE TABLE IF NOT EXISTS aivs_job_events (
        event_id UUID PRIMARY KEY,
        job_id UUID NOT NULL REFERENCES aivs_jobs(job_id) ON DELETE CASCADE,
        event_type TEXT NOT NULL,
        attempt INTEGER NOT NULL,
        message TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS aivs_job_events_job_created_idx
    ON aivs_job_events (job_id, created_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS aivs_job_idempotency (
        idempotency_hash TEXT PRIMARY KEY,
        job_id UUID NOT NULL UNIQUE REFERENCES aivs_jobs(job_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS aivs_usage (
        usage_id UUID PRIMARY KEY,
        job_id UUID NOT NULL UNIQUE REFERENCES aivs_jobs(job_id) ON DELETE CASCADE,
        stage TEXT NOT NULL,
        provider_id TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('succeeded', 'failed')),
        units DOUBLE PRECISION NOT NULL,
        duration_seconds INTEGER NOT NULL,
        created_at TIMESTAMPTZ NOT NULL
    )
    """,
)


def _safe_message(message: str) -> str:
    sanitized = _SECRET_RE.sub(r"\1=[REDACTED]", message.replace("\n", " "))
    return sanitized[:500]


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


def _as_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _as_uuid(value: Any) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


class PostgresUsageLedger:
    """Idempotent terminal usage records in PostgreSQL."""

    def __init__(self, connect: Callable[[], Any]) -> None:
        self._connect = connect

    @contextmanager
    def _session(self) -> Iterator[tuple[Any, Any]]:
        connection = self._connect()
        cursor = connection.cursor()
        try:
            yield connection, cursor
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
            connection.close()

    @staticmethod
    def _row_to_record(row: Any) -> UsageRecord:
        if isinstance(row, dict):
            values = row
        else:
            values = dict(
                zip(
                    (
                        "usage_id",
                        "job_id",
                        "stage",
                        "provider_id",
                        "status",
                        "units",
                        "duration_seconds",
                        "created_at",
                    ),
                    row,
                    strict=True,
                )
            )
        return UsageRecord(
            usage_id=_as_uuid(values["usage_id"]),
            job_id=_as_uuid(values["job_id"]),
            stage=values["stage"],
            provider_id=values["provider_id"],
            status=values["status"],
            units=values["units"],
            duration_seconds=values["duration_seconds"],
            created_at=_as_datetime(values["created_at"]),
        )

    def record(
        self,
        *,
        job_id: UUID,
        provider_id: str,
        status: str,
        duration_seconds: int,
    ) -> UsageRecord:
        with self._session() as (_connection, cursor):
            cursor.execute(
                """
                INSERT INTO aivs_usage
                    (usage_id, job_id, stage, provider_id, status, units,
                     duration_seconds, created_at)
                VALUES (%s, %s, 'pipeline', %s, %s, 1, %s, %s)
                ON CONFLICT (job_id) DO NOTHING
                """,
                (uuid4(), job_id, provider_id, status, duration_seconds, datetime.now(UTC)),
            )
            cursor.execute(
                """
                SELECT usage_id, job_id, stage, provider_id, status, units,
                       duration_seconds, created_at
                FROM aivs_usage WHERE job_id = %s
                """,
                (job_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("Postgres usage record disappeared during write")
            return self._row_to_record(row)

    def list(self) -> list[UsageRecord]:
        with self._session() as (_connection, cursor):
            cursor.execute(
                """
                SELECT usage_id, job_id, stage, provider_id, status, units,
                       duration_seconds, created_at
                FROM aivs_usage ORDER BY created_at DESC
                """
            )
            return [self._row_to_record(row) for row in cursor.fetchall()]

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


class PostgresJobStore:
    """A lease-based PostgreSQL queue with row-level claim locking."""

    def __init__(
        self,
        connect: Callable[[], Any],
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
        self._connect = connect
        self.root = root
        self.max_attempts = max_attempts
        self.lease_seconds = lease_seconds
        self.retry_backoff_seconds = retry_backoff_seconds
        self.artifacts_dir = root / "artifacts"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.usage = PostgresUsageLedger(connect)

    @classmethod
    def from_env(cls, root: Path | None = None) -> PostgresJobStore:
        connect = postgres_connect_from_env()
        storage_root = root or Path(os.getenv("AIVS_STORAGE_ROOT", ".aivs"))
        store = cls(
            connect,
            storage_root,
            max_attempts=_env_int("AIVS_JOB_MAX_ATTEMPTS", 3, 1, 100),
            lease_seconds=_env_int("AIVS_JOB_LEASE_SECONDS", 300, 5, 86_400),
            retry_backoff_seconds=_env_float("AIVS_JOB_RETRY_BACKOFF_SECONDS", 5.0, 0, 3_600),
        )
        store.ensure_schema()
        return store

    def _session(self) -> Any:
        return PostgresSession(self._connect)

    def ensure_schema(self) -> None:
        with self._session() as (_connection, cursor):
            for statement in SCHEMA_STATEMENTS:
                cursor.execute(statement)

    @staticmethod
    def _row_to_record(row: Any) -> JobRecord:
        if isinstance(row, dict):
            values = row
        else:
            values = dict(zip(_JOB_COLUMNS, row, strict=True))
        request_json = values["request_json"]
        if isinstance(request_json, str):
            request_json = json.loads(request_json)
        return JobRecord(
            job_id=_as_uuid(values["job_id"]),
            status=values["status"],
            request=CreateJobRequest.model_validate(request_json),
            attempt=values["attempt"],
            max_attempts=values["max_attempts"],
            created_at=_as_datetime(values["created_at"]),
            updated_at=_as_datetime(values["updated_at"]),
            next_retry_at=_as_datetime(values["next_retry_at"]),
            lease_expires_at=_as_datetime(values["lease_expires_at"]),
            plan_path=values["plan_path"],
            subtitle_path=values["subtitle_path"],
            audio_path=values["audio_path"],
            video_path=values["video_path"],
            social_drafts_path=values["social_drafts_path"],
            error_code=values["error_code"],
            error_message=values["error_message"],
        )

    @staticmethod
    def _record_values(record: JobRecord) -> tuple[Any, ...]:
        return (
            record.status,
            record.request.model_dump_json(),
            record.attempt,
            record.max_attempts,
            record.next_retry_at,
            record.lease_expires_at,
            record.plan_path,
            record.subtitle_path,
            record.audio_path,
            record.video_path,
            record.social_drafts_path,
            record.error_code,
            record.error_message,
            record.updated_at,
            record.job_id,
        )

    @staticmethod
    def _append_event(cursor: Any, record: JobRecord, event_type: str, message: str) -> None:
        event = JobEvent(
            job_id=record.job_id,
            event_type=event_type,  # type: ignore[arg-type] - validated by JobEvent
            attempt=record.attempt,
            message=_safe_message(message),
        )
        cursor.execute(
            """
            INSERT INTO aivs_job_events
                (event_id, job_id, event_type, attempt, message, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                event.event_id,
                event.job_id,
                event.event_type,
                event.attempt,
                event.message,
                event.created_at,
            ),
        )

    @staticmethod
    def _insert_job(cursor: Any, record: JobRecord) -> None:
        cursor.execute(
            """
            INSERT INTO aivs_jobs
                (job_id, status, request_json, attempt, max_attempts, created_at, updated_at,
                 next_retry_at, lease_expires_at, plan_path, subtitle_path, audio_path,
                 video_path, social_drafts_path, error_code, error_message)
            VALUES (%s, %s, CAST(%s AS jsonb), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                record.job_id,
                record.status,
                record.request.model_dump_json(),
                record.attempt,
                record.max_attempts,
                record.created_at,
                record.updated_at,
                record.next_retry_at,
                record.lease_expires_at,
                record.plan_path,
                record.subtitle_path,
                record.audio_path,
                record.video_path,
                record.social_drafts_path,
                record.error_code,
                record.error_message,
            ),
        )

    @classmethod
    def _select_record(
        cls, cursor: Any, job_id: UUID, *, for_update: bool = False
    ) -> JobRecord | None:
        suffix = " FOR UPDATE" if for_update else ""
        cursor.execute(
            f"SELECT {', '.join(_JOB_COLUMNS)} FROM aivs_jobs WHERE job_id = %s{suffix}",
            (job_id,),
        )
        row = cursor.fetchone()
        return None if row is None else cls._row_to_record(row)

    @classmethod
    def _update_record(cls, cursor: Any, record: JobRecord) -> None:
        record.updated_at = datetime.now(UTC)
        cursor.execute(
            """
            UPDATE aivs_jobs SET
                status = %s, request_json = CAST(%s AS jsonb), attempt = %s, max_attempts = %s,
                next_retry_at = %s, lease_expires_at = %s, plan_path = %s, subtitle_path = %s,
                audio_path = %s, video_path = %s, social_drafts_path = %s, error_code = %s,
                error_message = %s, updated_at = %s
            WHERE job_id = %s
            """,
            cls._record_values(record),
        )

    def create(
        self,
        request: CreateJobRequest,
        *,
        idempotency_key: str | None = None,
    ) -> JobRecord:
        normalized_key = (idempotency_key or "").strip()
        record = JobRecord(request=request, max_attempts=self.max_attempts)
        with self._session() as (_connection, cursor):
            if normalized_key:
                cursor.execute(
                    """
                    SELECT job_id FROM aivs_job_idempotency
                    WHERE idempotency_hash = %s FOR UPDATE
                    """,
                    (_fingerprint(normalized_key),),
                )
                existing = cursor.fetchone()
                if existing is not None:
                    found = self._select_record(cursor, _as_uuid(existing[0]))
                    if found is not None:
                        return found
            self._insert_job(cursor, record)
            if normalized_key:
                cursor.execute(
                    """
                    INSERT INTO aivs_job_idempotency (idempotency_hash, job_id)
                    VALUES (%s, %s) ON CONFLICT (idempotency_hash) DO NOTHING
                    """,
                    (_fingerprint(normalized_key), record.job_id),
                )
                if getattr(cursor, "rowcount", 1) == 0:
                    cursor.execute(
                        "SELECT job_id FROM aivs_job_idempotency WHERE idempotency_hash = %s",
                        (_fingerprint(normalized_key),),
                    )
                    existing = cursor.fetchone()
                    if existing is None:
                        raise RuntimeError("Postgres idempotency index is unavailable")
                    cursor.execute("DELETE FROM aivs_jobs WHERE job_id = %s", (record.job_id,))
                    found = self._select_record(cursor, _as_uuid(existing[0]))
                    if found is None:
                        raise RuntimeError("Postgres idempotent job disappeared during write")
                    return found
            self._append_event(cursor, record, "queued", "job accepted")
        return record

    def get(self, job_id: UUID) -> JobRecord | None:
        with self._session() as (_connection, cursor):
            return self._select_record(cursor, job_id)

    def save(self, record: JobRecord) -> JobRecord:
        with self._session() as (_connection, cursor):
            self._update_record(cursor, record)
        return record

    def recover_expired_leases(self) -> int:
        now = datetime.now(UTC)
        recovered = 0
        with self._session() as (_connection, cursor):
            cursor.execute(
                f"""
                SELECT {", ".join(_JOB_COLUMNS)} FROM aivs_jobs
                WHERE status = 'running' AND lease_expires_at IS NOT NULL AND lease_expires_at <= %s
                FOR UPDATE SKIP LOCKED
                """,
                (now,),
            )
            for row in cursor.fetchall():
                record = self._row_to_record(row)
                recovered += 1
                record.lease_expires_at = None
                record.error_code = "lease_expired"
                if record.attempt < record.max_attempts:
                    record.status = "queued"
                    record.next_retry_at = now
                    record.error_message = "worker lease expired; job requeued"
                    self._update_record(cursor, record)
                    self._append_event(cursor, record, "retrying", record.error_message)
                else:
                    record.status = "failed"
                    record.next_retry_at = None
                    record.error_message = "worker lease expired; retry budget exhausted"
                    self._update_record(cursor, record)
                    self._append_event(cursor, record, "failed", record.error_message)
                    self._record_usage(cursor, record, "pipeline", "failed")
        return recovered

    def claim_next(self) -> JobRecord | None:
        self.recover_expired_leases()
        now = datetime.now(UTC)
        with self._session() as (_connection, cursor):
            cursor.execute(
                f"""
                SELECT {", ".join(_JOB_COLUMNS)} FROM aivs_jobs
                WHERE status = 'queued' AND (next_retry_at IS NULL OR next_retry_at <= %s)
                ORDER BY created_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED
                """,
                (now,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            record = self._row_to_record(row)
            record.status = "running"
            record.attempt += 1
            record.next_retry_at = None
            record.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            record.error_code = None
            record.error_message = None
            self._update_record(cursor, record)
            self._append_event(cursor, record, "running", "worker claimed job")
            return record

    @staticmethod
    def _record_usage(cursor: Any, record: JobRecord, provider_id: str, status: str) -> None:
        cursor.execute(
            """
            INSERT INTO aivs_usage
                (usage_id, job_id, stage, provider_id, status, units, duration_seconds, created_at)
            VALUES (%s, %s, 'pipeline', %s, %s, 1, %s, %s)
            ON CONFLICT (job_id) DO NOTHING
            """,
            (
                uuid4(),
                record.job_id,
                provider_id,
                status,
                record.request.duration_seconds,
                datetime.now(UTC),
            ),
        )

    def finish(self, record: JobRecord, *, provider_id: str = "offline-renderer") -> JobRecord:
        record.lease_expires_at = None
        record.next_retry_at = None
        with self._session() as (_connection, cursor):
            self._update_record(cursor, record)
            if record.status == "succeeded":
                self._append_event(cursor, record, "succeeded", "render completed")
                self._record_usage(cursor, record, provider_id, "succeeded")
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
        record.error_message = _safe_message(error_message)
        record.lease_expires_at = None
        if retryable and record.attempt < record.max_attempts:
            delay = min(self.retry_backoff_seconds * (2 ** max(0, record.attempt - 1)), 3_600)
            record.status = "queued"
            record.next_retry_at = now + timedelta(seconds=delay)
            event_type = "retrying"
            event_message = f"{record.error_code}; retry scheduled"
        else:
            record.status = "failed"
            record.next_retry_at = None
            event_type = "failed"
            event_message = record.error_message or record.error_code
        with self._session() as (_connection, cursor):
            self._update_record(cursor, record)
            self._append_event(cursor, record, event_type, event_message)
            if record.status == "failed":
                self._record_usage(cursor, record, provider_id, "failed")
        return record

    def list_jobs(self, *, status: str | None = None, limit: int = 50) -> list[JobRecord]:
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        with self._session() as (_connection, cursor):
            if status is None:
                cursor.execute(
                    f"""
                    SELECT {", ".join(_JOB_COLUMNS)} FROM aivs_jobs
                    ORDER BY created_at DESC LIMIT %s
                    """,
                    (limit,),
                )
            else:
                cursor.execute(
                    f"""
                    SELECT {", ".join(_JOB_COLUMNS)} FROM aivs_jobs
                    WHERE status = %s ORDER BY created_at DESC LIMIT %s
                    """,
                    (status, limit),
                )
            return [self._row_to_record(row) for row in cursor.fetchall()]

    def events(self, job_id: UUID) -> list[JobEvent]:
        with self._session() as (_connection, cursor):
            cursor.execute(
                """
                SELECT event_id, job_id, event_type, attempt, message, created_at
                FROM aivs_job_events WHERE job_id = %s ORDER BY created_at ASC, event_id ASC
                """,
                (job_id,),
            )
            return [
                JobEvent(
                    event_id=_as_uuid(row[0]),
                    job_id=_as_uuid(row[1]),
                    event_type=row[2],
                    attempt=row[3],
                    message=row[4],
                    created_at=_as_datetime(row[5]),
                )
                for row in cursor.fetchall()
            ]

    def stats(self) -> dict[str, int]:
        with self._session() as (_connection, cursor):
            cursor.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE status = 'queued'),
                    COUNT(*) FILTER (WHERE status = 'running'),
                    COUNT(*) FILTER (WHERE status = 'succeeded'),
                    COUNT(*) FILTER (WHERE status = 'failed'),
                    COUNT(*) FILTER (WHERE status = 'queued')
                FROM aivs_jobs
                """
            )
            row = cursor.fetchone() or (0, 0, 0, 0, 0)
            return {
                "queued": int(row[0]),
                "running": int(row[1]),
                "succeeded": int(row[2]),
                "failed": int(row[3]),
                "queue_depth": int(row[4]),
            }


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


def postgres_connect_from_env() -> Callable[[], Any]:
    """Build a server-side PostgreSQL connection factory from ``AIVS_POSTGRES_DSN``."""

    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - exercised in deployment
        raise RuntimeError(
            "Postgres backend requires the optional dependency: pip install '.[postgres]'"
        ) from exc

    dsn = os.getenv("AIVS_POSTGRES_DSN", "").strip()
    if not dsn:
        raise RuntimeError("AIVS_POSTGRES_DSN must be configured for the Postgres backend")
    return lambda: psycopg.connect(dsn)


class PostgresSession:
    """Short-lived psycopg session used by metadata repositories.

    Keeping the connection lifecycle in one small helper lets the queue,
    catalogs and approval/audit repositories share the same safe pattern:
    synchronous service calls open a connection, commit or roll back one
    operation, then close it before returning to the request loop.
    """

    def __init__(self, connect: Callable[[], Any]) -> None:
        self._connect = connect
        self.connection: Any = None
        self.cursor: Any = None

    def __enter__(self) -> tuple[Any, Any]:
        self.connection = self._connect()
        self.cursor = self.connection.cursor()
        return self.connection, self.cursor

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        try:
            if exc_type is None:
                self.connection.commit()
            else:
                self.connection.rollback()
        finally:
            self.cursor.close()
            self.connection.close()
