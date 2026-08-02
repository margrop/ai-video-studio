"""PostgreSQL-backed approval history for distributed API deployments."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from packages.contracts.models import (
    PublishAuditRecord,
    SocialApprovalRecord,
    SocialApprovalRequest,
)
from packages.storage import PostgresSession, postgres_connect_from_env

from .approvals import ApprovalStore
from .audit import AuditStore

_APPROVAL_COLUMNS = (
    "approval_id",
    "job_id",
    "platform",
    "decision",
    "reviewer",
    "note",
    "created_at",
)
_AUDIT_COLUMNS = (
    "audit_id",
    "job_id",
    "platform",
    "action",
    "actor",
    "dry_run",
    "message",
    "external_id",
    "created_at",
)

APPROVAL_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS aivs_social_approvals (
        approval_id UUID PRIMARY KEY,
        job_id UUID NOT NULL,
        platform TEXT NOT NULL,
        decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
        reviewer TEXT NOT NULL,
        note TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS aivs_social_approvals_job_created_idx
    ON aivs_social_approvals (job_id, created_at)
    """,
)
AUDIT_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS aivs_publish_audit (
        audit_id UUID PRIMARY KEY,
        job_id UUID NOT NULL,
        platform TEXT NOT NULL,
        action TEXT NOT NULL,
        actor TEXT NOT NULL,
        dry_run BOOLEAN NOT NULL,
        message TEXT NOT NULL,
        external_id TEXT,
        created_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS aivs_publish_audit_job_created_idx
    ON aivs_publish_audit (job_id, created_at)
    """,
)


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _as_uuid(value: Any) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


class PostgresApprovalStore(ApprovalStore):
    """Append-only approval history stored in PostgreSQL."""

    def __init__(self, root: Path, connect: Callable[[], Any]) -> None:
        super().__init__(root)
        self._connect = connect

    @classmethod
    def from_env(cls, root: Path) -> PostgresApprovalStore:
        store = cls(root, postgres_connect_from_env())
        store.ensure_schema()
        return store

    def _session(self) -> PostgresSession:
        return PostgresSession(self._connect)

    def ensure_schema(self) -> None:
        with self._session() as (_connection, cursor):
            for statement in APPROVAL_SCHEMA_STATEMENTS:
                cursor.execute(statement)

    @staticmethod
    def _row_to_record(row: Any) -> SocialApprovalRecord:
        values = row if isinstance(row, dict) else dict(zip(_APPROVAL_COLUMNS, row, strict=True))
        return SocialApprovalRecord(
            approval_id=_as_uuid(values["approval_id"]),
            job_id=_as_uuid(values["job_id"]),
            platform=values["platform"],
            decision=values["decision"],
            reviewer=values["reviewer"],
            note=values["note"],
            created_at=_as_datetime(values["created_at"]),
        )

    def list(self, job_id: UUID) -> list[SocialApprovalRecord]:
        with self._session() as (_connection, cursor):
            cursor.execute(
                f"SELECT {', '.join(_APPROVAL_COLUMNS)} FROM aivs_social_approvals "
                "WHERE job_id = %s ORDER BY created_at ASC, approval_id ASC",
                (job_id,),
            )
            return [self._row_to_record(row) for row in cursor.fetchall()]

    def decide(self, job_id: UUID, request: SocialApprovalRequest) -> SocialApprovalRecord:
        record = SocialApprovalRecord(job_id=job_id, **request.model_dump())
        with self._session() as (_connection, cursor):
            cursor.execute(
                """
                INSERT INTO aivs_social_approvals
                    (approval_id, job_id, platform, decision, reviewer, note, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    record.approval_id,
                    record.job_id,
                    record.platform,
                    record.decision,
                    record.reviewer,
                    record.note,
                    record.created_at,
                ),
            )
        return record


class PostgresAuditStore(AuditStore):
    """Append-only publish audit log stored in PostgreSQL."""

    def __init__(self, root: Path, connect: Callable[[], Any]) -> None:
        super().__init__(root)
        self._connect = connect

    @classmethod
    def from_env(cls, root: Path) -> PostgresAuditStore:
        store = cls(root, postgres_connect_from_env())
        store.ensure_schema()
        return store

    def _session(self) -> PostgresSession:
        return PostgresSession(self._connect)

    def ensure_schema(self) -> None:
        with self._session() as (_connection, cursor):
            for statement in AUDIT_SCHEMA_STATEMENTS:
                cursor.execute(statement)

    @staticmethod
    def _row_to_record(row: Any) -> PublishAuditRecord:
        values = row if isinstance(row, dict) else dict(zip(_AUDIT_COLUMNS, row, strict=True))
        return PublishAuditRecord(
            audit_id=_as_uuid(values["audit_id"]),
            job_id=_as_uuid(values["job_id"]),
            platform=values["platform"],
            action=values["action"],
            actor=values["actor"],
            dry_run=bool(values["dry_run"]),
            message=values["message"],
            external_id=values["external_id"],
            created_at=_as_datetime(values["created_at"]),
        )

    def list(self, job_id: UUID) -> list[PublishAuditRecord]:
        with self._session() as (_connection, cursor):
            cursor.execute(
                f"SELECT {', '.join(_AUDIT_COLUMNS)} FROM aivs_publish_audit "
                "WHERE job_id = %s ORDER BY created_at ASC, audit_id ASC",
                (job_id,),
            )
            return [self._row_to_record(row) for row in cursor.fetchall()]

    def record(self, event: PublishAuditRecord) -> PublishAuditRecord:
        with self._session() as (_connection, cursor):
            cursor.execute(
                """
                INSERT INTO aivs_publish_audit
                    (audit_id, job_id, platform, action, actor, dry_run, message,
                     external_id, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    event.audit_id,
                    event.job_id,
                    event.platform,
                    event.action,
                    event.actor,
                    event.dry_run,
                    event.message,
                    event.external_id,
                    event.created_at,
                ),
            )
        return event


def _configured_backend(name: str) -> str:
    configured = os.getenv(name, "").strip().lower()
    if configured:
        return configured
    return (
        "postgres"
        if os.getenv("AIVS_STORAGE_BACKEND", "").strip().lower()
        in {
            "postgres",
            "postgresql",
        }
        else "filesystem"
    )


def build_approval_store(root: Path) -> ApprovalStore:
    """Build local or PostgreSQL approval persistence from server configuration."""

    backend = _configured_backend("AIVS_APPROVAL_BACKEND")
    if backend in {"filesystem", "file", "local"}:
        return ApprovalStore(root)
    if backend in {"postgres", "postgresql"}:
        store = PostgresApprovalStore(root, postgres_connect_from_env())
        store.ensure_schema()
        return store
    raise ValueError("AIVS_APPROVAL_BACKEND must be filesystem or postgres")


def build_audit_store(root: Path) -> AuditStore:
    """Build local or PostgreSQL audit persistence from server configuration."""

    backend = _configured_backend("AIVS_AUDIT_BACKEND")
    if backend in {"filesystem", "file", "local"}:
        return AuditStore(root)
    if backend in {"postgres", "postgresql"}:
        store = PostgresAuditStore(root, postgres_connect_from_env())
        store.ensure_schema()
        return store
    raise ValueError("AIVS_AUDIT_BACKEND must be filesystem or postgres")
