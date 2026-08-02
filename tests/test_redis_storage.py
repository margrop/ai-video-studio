"""Redis backend tests use a small in-memory Redis-compatible client."""

from __future__ import annotations

import fnmatch
from datetime import UTC, datetime, timedelta

from packages.contracts.models import CreateJobRequest
from packages.storage import RedisJobStore


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}
        self.sorted_sets: dict[str, dict[str, float]] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(
        self,
        key: str,
        value: str,
        nx: bool = False,
        ex: int | None = None,
    ) -> bool | None:
        del ex
        if nx and key in self.values:
            return False
        self.values[key] = str(value)
        return True

    def delete(self, key: str) -> int:
        existed = int(key in self.values or key in self.lists or key in self.sorted_sets)
        self.values.pop(key, None)
        self.lists.pop(key, None)
        self.sorted_sets.pop(key, None)
        return existed

    def rpush(self, key: str, value: str) -> int:
        self.lists.setdefault(key, []).append(str(value))
        return len(self.lists[key])

    def rpoplpush(self, source: str, destination: str) -> str | None:
        values = self.lists.setdefault(source, [])
        if not values:
            return None
        value = values.pop()
        self.lists.setdefault(destination, []).insert(0, value)
        return value

    def lrange(self, key: str, start: int, stop: int) -> list[str]:
        values = self.lists.get(key, [])
        end = None if stop == -1 else stop + 1
        return values[start:end]

    def lrem(self, key: str, count: int, value: str) -> int:
        values = self.lists.get(key, [])
        original = len(values)
        if count == 0:
            self.lists[key] = [item for item in values if item != value]
        elif count > 0:
            removed = 0
            kept: list[str] = []
            for item in values:
                if item == value and removed < count:
                    removed += 1
                else:
                    kept.append(item)
            self.lists[key] = kept
        else:
            removed = 0
            kept = []
            for item in reversed(values):
                if item == value and removed < abs(count):
                    removed += 1
                else:
                    kept.append(item)
            self.lists[key] = list(reversed(kept))
        return original - len(self.lists[key])

    def zadd(self, key: str, values: dict[str, float]) -> int:
        target = self.sorted_sets.setdefault(key, {})
        added = 0
        for member, score in values.items():
            if member not in target:
                added += 1
            target[member] = float(score)
        return added

    def zrem(self, key: str, member: str) -> int:
        target = self.sorted_sets.setdefault(key, {})
        return int(target.pop(member, None) is not None)

    def zrange(self, key: str, start: int, stop: int) -> list[str]:
        members = sorted(self.sorted_sets.get(key, {}).items(), key=lambda item: (item[1], item[0]))
        selected = [member for member, _score in members]
        return selected[start:] if stop == -1 else selected[start : stop + 1]

    def zrangebyscore(self, key: str, minimum: str | float, maximum: str | float) -> list[str]:
        upper = float("inf") if maximum == "+inf" else float(maximum)
        lower = float("-inf") if minimum == "-inf" else float(minimum)
        return [
            member
            for member, score in sorted(self.sorted_sets.get(key, {}).items())
            if lower <= score <= upper
        ]

    def zcard(self, key: str) -> int:
        return len(self.sorted_sets.get(key, {}))

    def llen(self, key: str) -> int:
        return len(self.lists.get(key, []))

    def scan_iter(self, match: str):
        keys = set(self.values) | set(self.lists) | set(self.sorted_sets)
        yield from sorted(key for key in keys if fnmatch.fnmatch(key, match))


def test_redis_store_transitions_and_idempotency(tmp_path) -> None:
    store = RedisJobStore(FakeRedis(), tmp_path / "state", retry_backoff_seconds=0)
    request = CreateJobRequest(topic="Redis synthetic", use_ai=False)

    first = store.create(request, idempotency_key="redis-1")
    duplicate = store.create(request, idempotency_key="redis-1")
    assert duplicate.job_id == first.job_id
    assert store.stats()["queue_depth"] == 1

    claimed = store.claim_next()
    assert claimed is not None
    assert claimed.status == "running"
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


def test_redis_store_retries_and_recovers_expired_leases(tmp_path) -> None:
    store = RedisJobStore(
        FakeRedis(),
        tmp_path / "state",
        max_attempts=3,
        lease_seconds=5,
        retry_backoff_seconds=0,
    )
    created = store.create(CreateJobRequest(topic="Redis retry", use_ai=False))
    first = store.claim_next()
    assert first is not None
    first.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    store.save(first)
    assert store.recover_expired_leases() == 1
    assert store.get(created.job_id).status == "queued"

    second = store.claim_next()
    assert second is not None
    retried = store.fail(
        second,
        error_code="synthetic_failure",
        error_message="provider token=never-store",
    )
    assert retried.status == "queued"
    assert retried.error_message == "provider token=[REDACTED]"
    third = store.claim_next()
    assert third is not None
    exhausted = store.fail(
        third,
        error_code="synthetic_failure",
        error_message="still unavailable",
    )
    assert exhausted.status == "failed"
    assert store.usage.summary().failed_jobs == 1


def test_redis_store_keeps_a_processing_handoff_recoverable(tmp_path) -> None:
    store = RedisJobStore(FakeRedis(), tmp_path / "state")
    created = store.create(CreateJobRequest(topic="Handoff", use_ai=False))
    claimed = store.claim_next()
    assert claimed is not None

    # Simulate a worker that wrote a queued state but died before removing
    # the reliable processing-list entry.
    claimed.status = "queued"
    claimed.lease_expires_at = None
    store.save(claimed)
    assert store.recover_expired_leases() == 0
    assert store.claim_next() is not None
    assert store.get(created.job_id).status == "running"
