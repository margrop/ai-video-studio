"""Select the queue backend from service-owned environment configuration."""

from __future__ import annotations

import os
from pathlib import Path

from packages.storage.jobs import FileJobStore
from packages.storage.protocols import JobStore
from packages.storage.redis import RedisJobStore


def build_job_store(root: Path | None = None) -> JobStore:
    """Build the configured backend; filesystem remains the safe default."""

    backend = os.getenv("AIVS_STORAGE_BACKEND", "filesystem").strip().lower()
    if backend in {"filesystem", "file", "local"}:
        return FileJobStore.from_env(root)
    if backend == "redis":
        return RedisJobStore.from_env(root)
    raise ValueError("AIVS_STORAGE_BACKEND must be filesystem or redis")
