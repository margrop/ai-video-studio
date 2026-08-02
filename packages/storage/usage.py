"""Small idempotent usage ledger for local operations and future billing hooks."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from uuid import UUID

from packages.contracts.models import UsageRecord, UsageSummary


class UsageLedger:
    """Keep one terminal usage record per job so retries do not double count."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, job_id: UUID) -> Path:
        return self.root / f"{job_id}.json"

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            Path(temporary_name).replace(path)
        finally:
            temporary = Path(temporary_name)
            if temporary.exists():
                temporary.unlink()

    def record(
        self,
        *,
        job_id: UUID,
        provider_id: str,
        status: str,
        duration_seconds: int,
    ) -> UsageRecord:
        record = UsageRecord(
            job_id=job_id,
            provider_id=provider_id,
            status=status,  # type: ignore[arg-type] - validated by UsageRecord
            duration_seconds=duration_seconds,
        )
        self._atomic_write(self._path(job_id), record.model_dump_json(indent=2))
        return record

    def list(self) -> list[UsageRecord]:
        records: list[UsageRecord] = []
        for path in self.root.glob("*.json"):
            try:
                records.append(UsageRecord.model_validate_json(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
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
