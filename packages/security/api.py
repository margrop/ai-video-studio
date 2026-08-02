"""Optional API-key authentication and process/Redis rate limiting.

The local default remains convenient: an empty ``AIVS_API_KEY`` permits local
development. Once a key is configured, every ``/v1`` route requires either a
Bearer token or ``X-AIVS-API-Key``. Secrets are compared in constant time and
never included in responses.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if minimum <= value <= maximum else default


@dataclass(frozen=True, slots=True)
class APIAuthenticator:
    """Validate a single service-owned API key without exposing it."""

    api_key: str | None = None

    @classmethod
    def from_env(cls) -> APIAuthenticator:
        value = os.getenv("AIVS_API_KEY", "").strip()
        return cls(api_key=value or None)

    @property
    def enabled(self) -> bool:
        return self.api_key is not None

    def allows(self, *, authorization: str | None, api_key_header: str | None) -> bool:
        if self.api_key is None:
            return True
        candidate = (api_key_header or "").strip()
        if not candidate and authorization:
            scheme, _, token = authorization.partition(" ")
            if scheme.lower() == "bearer":
                candidate = token.strip()
        if not candidate:
            return False
        return hmac.compare_digest(candidate, self.api_key)


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int = 0


class RateLimiter(Protocol):
    def check(self, key: str, *, now: float | None = None) -> RateLimitDecision: ...


class _NoopRateLimiter:
    def check(self, key: str, *, now: float | None = None) -> RateLimitDecision:
        del key, now
        return RateLimitDecision(allowed=True, limit=0, remaining=0)


class FixedWindowRateLimiter:
    """Small single-process limiter used by the filesystem backend."""

    def __init__(self, limit: int, window_seconds: int) -> None:
        if limit < 1:
            raise ValueError("limit must be positive")
        if window_seconds < 1:
            raise ValueError("window_seconds must be positive")
        self.limit = limit
        self.window_seconds = window_seconds
        self._buckets: dict[tuple[str, int], int] = {}
        self._lock = threading.Lock()

    def check(self, key: str, *, now: float | None = None) -> RateLimitDecision:
        timestamp = time.time() if now is None else now
        bucket = int(timestamp // self.window_seconds)
        bucket_key = (key, bucket)
        with self._lock:
            count = self._buckets.get(bucket_key, 0) + 1
            self._buckets[bucket_key] = count
            if len(self._buckets) > 10_000:
                current_bucket = bucket
                self._buckets = {
                    item: value
                    for item, value in self._buckets.items()
                    if item[1] >= current_bucket - 1
                }
        remaining = max(0, self.limit - count)
        retry_after = max(
            1,
            math.ceil((bucket + 1) * self.window_seconds - timestamp),
        )
        return RateLimitDecision(
            allowed=count <= self.limit,
            limit=self.limit,
            remaining=remaining,
            retry_after_seconds=retry_after if count > self.limit else 0,
        )


class RedisRateLimiter:
    """Fixed-window limiter shared by API replicas through Redis."""

    def __init__(
        self,
        client: Any,
        *,
        prefix: str,
        limit: int,
        window_seconds: int,
        fallback: FixedWindowRateLimiter,
    ) -> None:
        self.client = client
        self.prefix = prefix
        self.limit = limit
        self.window_seconds = window_seconds
        self.fallback = fallback

    def check(self, key: str, *, now: float | None = None) -> RateLimitDecision:
        timestamp = time.time() if now is None else now
        bucket = int(timestamp // self.window_seconds)
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        redis_key = f"{self.prefix}{digest}:{bucket}"
        try:
            count = int(self.client.incr(redis_key))
            if count == 1:
                self.client.expire(redis_key, self.window_seconds + 1)
        except Exception:  # noqa: BLE001 - preserve availability if Redis is down.
            return self.fallback.check(key, now=timestamp)

        remaining = max(0, self.limit - count)
        retry_after = max(
            1,
            math.ceil((bucket + 1) * self.window_seconds - timestamp),
        )
        return RateLimitDecision(
            allowed=count <= self.limit,
            limit=self.limit,
            remaining=remaining,
            retry_after_seconds=retry_after if count > self.limit else 0,
        )


def build_rate_limiter(store: Any) -> RateLimiter:
    """Use Redis counters when available, otherwise a bounded local limiter."""

    limit = _env_int("AIVS_RATE_LIMIT_PER_MINUTE", 120, 0, 100_000)
    if limit == 0:
        return _NoopRateLimiter()
    window_seconds = _env_int("AIVS_RATE_LIMIT_WINDOW_SECONDS", 60, 1, 3_600)
    fallback = FixedWindowRateLimiter(limit, window_seconds)
    client = getattr(store, "client", None)
    if client is None:
        return fallback
    return RedisRateLimiter(
        client,
        prefix=f"{getattr(store, 'namespace', 'aivs')}:ratelimit:",
        limit=limit,
        window_seconds=window_seconds,
        fallback=fallback,
    )


def security_headers(decision: RateLimitDecision) -> dict[str, str]:
    """Return stable rate-limit headers without exposing internal state."""

    if decision.limit == 0:
        return {}
    headers = {
        "X-RateLimit-Limit": str(decision.limit),
        "X-RateLimit-Remaining": str(decision.remaining),
    }
    if decision.retry_after_seconds:
        headers["Retry-After"] = str(decision.retry_after_seconds)
    return headers
