"""Append-only audit records for agent and API publishing actions."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from uuid import UUID

from packages.contracts.models import PublishAuditRecord


class AuditStore:
    """Persist safe publish events without storing credentials or payloads."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, job_id: UUID) -> Path:
        return self.root / f"{job_id}.jsonl"

    @staticmethod
    def _append(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "a", encoding="utf-8") as handle:
                if path.exists():
                    handle.write(path.read_text(encoding="utf-8"))
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            Path(temporary_name).replace(path)
        finally:
            temporary = Path(temporary_name)
            if temporary.exists():
                temporary.unlink()

    def list(self, job_id: UUID) -> list[PublishAuditRecord]:
        path = self._path(job_id)
        if not path.exists():
            return []
        records: list[PublishAuditRecord] = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        for line in lines:
            try:
                records.append(PublishAuditRecord.model_validate_json(line))
            except ValueError:
                continue
        return records

    def record(self, event: PublishAuditRecord) -> PublishAuditRecord:
        self._append(self._path(event.job_id), event.model_dump_json() + "\n")
        return event
