from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from packages.contracts.models import CreateJobRequest
from packages.storage import PostgresJobStore


class FakePostgres:
    def __init__(self) -> None:
        self.jobs: dict[UUID, dict[str, Any]] = {}
        self.idempotency: dict[str, UUID] = {}
        self.events: list[dict[str, Any]] = []
        self.usage: dict[UUID, dict[str, Any]] = {}
        self.schema_statements: list[str] = []

    def connect(self) -> FakeConnection:
        return FakeConnection(self)


class FakeConnection:
    def __init__(self, database: FakePostgres) -> None:
        self.database = database
        self.closed = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.database)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class FakeCursor:
    def __init__(self, database: FakePostgres) -> None:
        self.database = database
        self.rowcount = -1
        self.rows: list[Any] = []

    @staticmethod
    def _normalized(query: str) -> str:
        return " ".join(query.split()).lower()

    @staticmethod
    def _job_row(job: dict[str, Any]) -> tuple[Any, ...]:
        return tuple(
            job[name]
            for name in (
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
        )

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        normalized = self._normalized(query)
        self.rows = []
        self.rowcount = -1
        if normalized.startswith("create "):
            self.database.schema_statements.append(query)
            return

        if normalized.startswith("insert into aivs_jobs"):
            values = list(params)
            names = (
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
            self.database.jobs[values[0]] = dict(zip(names, values, strict=True))
            self.rowcount = 1
            return

        if normalized.startswith("insert into aivs_job_idempotency"):
            key, job_id = params
            if key in self.database.idempotency:
                self.rowcount = 0
            else:
                self.database.idempotency[key] = job_id
                self.rowcount = 1
            return

        if normalized.startswith("insert into aivs_job_events"):
            event_id, job_id, event_type, attempt, message, created_at = params
            self.database.events.append(
                {
                    "event_id": event_id,
                    "job_id": job_id,
                    "event_type": event_type,
                    "attempt": attempt,
                    "message": message,
                    "created_at": created_at,
                }
            )
            self.rowcount = 1
            return

        if normalized.startswith("insert into aivs_usage"):
            usage_id, job_id, provider_id, status, duration_seconds, created_at = params
            if job_id in self.database.usage:
                self.rowcount = 0
            else:
                self.database.usage[job_id] = {
                    "usage_id": usage_id,
                    "job_id": job_id,
                    "stage": "pipeline",
                    "provider_id": provider_id,
                    "status": status,
                    "units": 1,
                    "duration_seconds": duration_seconds,
                    "created_at": created_at,
                }
                self.rowcount = 1
            return

        if normalized.startswith("update aivs_jobs set"):
            values = list(params)
            job_id = values[-1]
            job = self.database.jobs[job_id]
            for name, value in zip(
                (
                    "status",
                    "request_json",
                    "attempt",
                    "max_attempts",
                    "next_retry_at",
                    "lease_expires_at",
                    "plan_path",
                    "subtitle_path",
                    "audio_path",
                    "video_path",
                    "social_drafts_path",
                    "error_code",
                    "error_message",
                    "updated_at",
                ),
                values[:-1],
                strict=True,
            ):
                job[name] = value
            self.rowcount = 1
            return

        if normalized.startswith("delete from aivs_jobs"):
            self.database.jobs.pop(params[0], None)
            self.rowcount = 1
            return

        if normalized.startswith("select job_id from aivs_job_idempotency"):
            job_id = self.database.idempotency.get(params[0])
            self.rows = [] if job_id is None else [(job_id,)]
            return

        if normalized.startswith("select usage_id, job_id"):
            if "where job_id" in normalized:
                usage = self.database.usage.get(params[0])
                self.rows = [] if usage is None else [self._usage_row(usage)]
            else:
                self.rows = [self._usage_row(item) for item in self.database.usage.values()]
            return

        if normalized.startswith("select event_id, job_id"):
            job_id = params[0]
            self.rows = [
                (
                    event["event_id"],
                    event["job_id"],
                    event["event_type"],
                    event["attempt"],
                    event["message"],
                    event["created_at"],
                )
                for event in self.database.events
                if event["job_id"] == job_id
            ]
            self.rows.sort(key=lambda row: (row[5], str(row[0])))
            return

        if normalized.startswith("select count(*) filter"):
            counts = {
                status: sum(job["status"] == status for job in self.database.jobs.values())
                for status in ("queued", "running", "succeeded", "failed")
            }
            self.rows = [
                (
                    counts["queued"],
                    counts["running"],
                    counts["succeeded"],
                    counts["failed"],
                    counts["queued"],
                )
            ]
            return

        if normalized.startswith("select") and "from aivs_jobs" in normalized:
            jobs = list(self.database.jobs.values())
            if "where job_id" in normalized:
                jobs = [job for job in jobs if job["job_id"] == params[0]]
            elif "status = 'running'" in normalized:
                now = params[0]
                jobs = [
                    job
                    for job in jobs
                    if job["status"] == "running"
                    and job["lease_expires_at"] is not None
                    and job["lease_expires_at"] <= now
                ]
            elif "status = 'queued'" in normalized:
                now = params[0]
                jobs = [
                    job
                    for job in jobs
                    if job["status"] == "queued"
                    and (job["next_retry_at"] is None or job["next_retry_at"] <= now)
                ]
                jobs.sort(key=lambda job: job["created_at"])
                jobs = jobs[:1]
            elif "where status = %s" in normalized:
                status, limit = params
                jobs = [job for job in jobs if job["status"] == status]
                jobs.sort(key=lambda job: job["created_at"], reverse=True)
                jobs = jobs[:limit]
            else:
                limit = params[0]
                jobs.sort(key=lambda job: job["created_at"], reverse=True)
                jobs = jobs[:limit]
            self.rows = [self._job_row(job) for job in jobs]
            return

        raise AssertionError(f"unhandled SQL: {query}")

    @staticmethod
    def _usage_row(usage: dict[str, Any]) -> tuple[Any, ...]:
        return tuple(
            usage[name]
            for name in (
                "usage_id",
                "job_id",
                "stage",
                "provider_id",
                "status",
                "units",
                "duration_seconds",
                "created_at",
            )
        )

    def fetchone(self) -> Any:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[Any]:
        return self.rows

    def close(self) -> None:
        return None


def build_store(tmp_path) -> tuple[PostgresJobStore, FakePostgres]:
    database = FakePostgres()
    store = PostgresJobStore(database.connect, tmp_path / "state", retry_backoff_seconds=0)
    store.ensure_schema()
    return store, database


def test_postgres_store_transitions_and_idempotency(tmp_path) -> None:
    store, database = build_store(tmp_path)
    request = CreateJobRequest(topic="Postgres synthetic", use_ai=False)

    first = store.create(request, idempotency_key="postgres-1")
    duplicate = store.create(request, idempotency_key="postgres-1")
    assert duplicate.job_id == first.job_id
    assert len(database.jobs) == 1
    assert store.stats()["queue_depth"] == 1

    claimed = store.claim_next()
    assert claimed is not None
    claimed.status = "succeeded"
    store.finish(claimed, provider_id="offline-renderer")

    assert [event.event_type for event in store.events(first.job_id)] == [
        "queued",
        "running",
        "succeeded",
    ]
    assert store.stats() == {
        "queued": 0,
        "running": 0,
        "succeeded": 1,
        "failed": 0,
        "queue_depth": 0,
    }
    assert store.usage.summary().successful_jobs == 1


def test_postgres_store_retries_and_redacts_failures(tmp_path) -> None:
    store, _database = build_store(tmp_path)
    created = store.create(CreateJobRequest(topic="Postgres retry", use_ai=False))
    first = store.claim_next()
    assert first is not None

    retried = store.fail(
        first,
        error_code="synthetic_failure",
        error_message="provider token=never-store",
    )
    assert retried.status == "queued"
    assert retried.error_message == "provider token=[REDACTED]"

    second = store.claim_next()
    assert second is not None
    exhausted = store.fail(
        second,
        error_code="synthetic_failure",
        error_message="still unavailable",
        retryable=False,
    )
    assert exhausted.status == "failed"
    assert store.usage.summary().failed_jobs == 1
    assert store.get(created.job_id).status == "failed"


def test_postgres_store_recovers_expired_lease(tmp_path) -> None:
    store, _database = build_store(tmp_path)
    created = store.create(CreateJobRequest(topic="Postgres lease", use_ai=False))
    claimed = store.claim_next()
    assert claimed is not None
    claimed.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    store.save(claimed)

    assert store.recover_expired_leases() == 1
    recovered = store.get(created.job_id)
    assert recovered is not None
    assert recovered.status == "queued"
    assert recovered.error_code == "lease_expired"
