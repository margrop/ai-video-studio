"""Auditable human approval records for generated social drafts."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from uuid import UUID

from packages.contracts.models import SocialApprovalRecord, SocialApprovalRequest


class ApprovalStore:
    """Persist append-only approval decisions below a server-owned root."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, job_id: UUID) -> Path:
        return self.root / f"{job_id}.json"

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
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

    def list(self, job_id: UUID) -> list[SocialApprovalRecord]:
        path = self._path(job_id)
        if not path.exists():
            return []
        try:
            raw = path.read_text(encoding="utf-8")
            values = json.loads(raw)
        except (OSError, ValueError):
            return []
        if not isinstance(values, list):
            return []
        records: list[SocialApprovalRecord] = []
        for value in values:
            try:
                records.append(SocialApprovalRecord.model_validate(value))
            except ValueError:
                continue
        return records

    def decide(self, job_id: UUID, request: SocialApprovalRequest) -> SocialApprovalRecord:
        record = SocialApprovalRecord(job_id=job_id, **request.model_dump())
        records = self.list(job_id)
        records.append(record)
        self._atomic_write(
            self._path(job_id),
            "[\n" + ",\n".join(item.model_dump_json(indent=2) for item in records) + "\n]\n",
        )
        return record

    def latest(self, job_id: UUID) -> dict[str, SocialApprovalRecord]:
        latest: dict[str, SocialApprovalRecord] = {}
        for record in self.list(job_id):
            latest[record.platform] = record
        return latest
