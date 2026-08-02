from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from packages.contracts.models import (
    CreateAssetRequest,
    CreateCharacterRequest,
    PublishAuditRecord,
    SocialApprovalRequest,
)
from packages.library import PostgresAssetCatalog, PostgresCharacterCatalog
from packages.publishing import PostgresApprovalStore, PostgresAuditStore


class FakeMetadataDatabase:
    def __init__(self) -> None:
        self.assets: dict[UUID, dict[str, Any]] = {}
        self.characters: dict[UUID, dict[str, Any]] = {}
        self.approvals: list[dict[str, Any]] = []
        self.audit: list[dict[str, Any]] = []
        self.schema_statements: list[str] = []

    def connect(self) -> FakeMetadataConnection:
        return FakeMetadataConnection(self)


class FakeMetadataConnection:
    def __init__(self, database: FakeMetadataDatabase) -> None:
        self.database = database

    def cursor(self) -> FakeMetadataCursor:
        return FakeMetadataCursor(self.database)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


class FakeMetadataCursor:
    def __init__(self, database: FakeMetadataDatabase) -> None:
        self.database = database
        self.rows: list[Any] = []

    @staticmethod
    def _normalized(query: str) -> str:
        return " ".join(query.split()).lower()

    @staticmethod
    def _asset_row(record: dict[str, Any]) -> tuple[Any, ...]:
        return tuple(
            record[column]
            for column in (
                "asset_id",
                "name",
                "kind",
                "storage_key",
                "mime_type",
                "tags",
                "size_bytes",
                "sha256",
                "created_at",
                "updated_at",
            )
        )

    @staticmethod
    def _character_row(record: dict[str, Any]) -> tuple[Any, ...]:
        return tuple(
            record[column]
            for column in (
                "character_id",
                "name",
                "description",
                "prompt",
                "voice",
                "language",
                "reference_asset_ids",
                "created_at",
                "updated_at",
            )
        )

    @staticmethod
    def _approval_row(record: dict[str, Any]) -> tuple[Any, ...]:
        return tuple(
            record[column]
            for column in (
                "approval_id",
                "job_id",
                "platform",
                "decision",
                "reviewer",
                "note",
                "created_at",
            )
        )

    @staticmethod
    def _audit_row(record: dict[str, Any]) -> tuple[Any, ...]:
        return tuple(
            record[column]
            for column in (
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
        )

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        normalized = self._normalized(query)
        self.rows = []
        if normalized.startswith("create "):
            self.database.schema_statements.append(query)
            return

        if normalized.startswith("insert into aivs_assets"):
            (
                asset_id,
                name,
                kind,
                storage_key,
                mime_type,
                tags,
                size_bytes,
                sha256,
                created_at,
                updated_at,
            ) = params
            self.database.assets[asset_id] = {
                "asset_id": asset_id,
                "name": name,
                "kind": kind,
                "storage_key": storage_key,
                "mime_type": mime_type,
                "tags": tags,
                "size_bytes": size_bytes,
                "sha256": sha256,
                "created_at": created_at,
                "updated_at": updated_at,
            }
            return

        if normalized.startswith("select asset_id,"):
            records = list(self.database.assets.values())
            if "where asset_id" in normalized:
                records = [record for record in records if record["asset_id"] == params[0]]
            else:
                records.sort(key=lambda record: record["created_at"], reverse=True)
                records = records[: params[0]]
            self.rows = [self._asset_row(record) for record in records]
            return

        if normalized.startswith("insert into aivs_characters"):
            (
                character_id,
                name,
                description,
                prompt,
                voice,
                language,
                reference_asset_ids,
                created_at,
                updated_at,
            ) = params
            self.database.characters[character_id] = {
                "character_id": character_id,
                "name": name,
                "description": description,
                "prompt": prompt,
                "voice": voice,
                "language": language,
                "reference_asset_ids": reference_asset_ids,
                "created_at": created_at,
                "updated_at": updated_at,
            }
            return

        if normalized.startswith("select character_id,"):
            records = list(self.database.characters.values())
            if "where character_id" in normalized:
                records = [record for record in records if record["character_id"] == params[0]]
            else:
                records.sort(key=lambda record: record["created_at"], reverse=True)
                records = records[: params[0]]
            self.rows = [self._character_row(record) for record in records]
            return

        if normalized.startswith("insert into aivs_social_approvals"):
            approval_id, job_id, platform, decision, reviewer, note, created_at = params
            self.database.approvals.append(
                {
                    "approval_id": approval_id,
                    "job_id": job_id,
                    "platform": platform,
                    "decision": decision,
                    "reviewer": reviewer,
                    "note": note,
                    "created_at": created_at,
                }
            )
            return

        if normalized.startswith("select approval_id,"):
            job_id = params[0]
            records = [record for record in self.database.approvals if record["job_id"] == job_id]
            records.sort(key=lambda record: (record["created_at"], str(record["approval_id"])))
            self.rows = [self._approval_row(record) for record in records]
            return

        if normalized.startswith("insert into aivs_publish_audit"):
            (
                audit_id,
                job_id,
                platform,
                action,
                actor,
                dry_run,
                message,
                external_id,
                created_at,
            ) = params
            self.database.audit.append(
                {
                    "audit_id": audit_id,
                    "job_id": job_id,
                    "platform": platform,
                    "action": action,
                    "actor": actor,
                    "dry_run": dry_run,
                    "message": message,
                    "external_id": external_id,
                    "created_at": created_at,
                }
            )
            return

        if normalized.startswith("select audit_id,"):
            job_id = params[0]
            records = [record for record in self.database.audit if record["job_id"] == job_id]
            records.sort(key=lambda record: (record["created_at"], str(record["audit_id"])))
            self.rows = [self._audit_row(record) for record in records]
            return

        raise AssertionError(f"unhandled SQL: {query}")

    def fetchone(self) -> Any:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[Any]:
        return self.rows

    def close(self) -> None:
        return None


def test_postgres_catalogs_share_metadata_and_validate_references(tmp_path) -> None:
    database = FakeMetadataDatabase()
    assets = PostgresAssetCatalog(tmp_path / "assets", database.connect)
    characters = PostgresCharacterCatalog(tmp_path / "characters", assets, database.connect)
    assets.ensure_schema()
    characters.ensure_schema()

    asset = assets.create(CreateAssetRequest(name="Logo", kind="logo", tags=["brand"]))
    character = characters.create(
        CreateCharacterRequest(
            name="Host",
            prompt="consistent technology host",
            reference_asset_ids=[asset.asset_id],
        )
    )

    assert assets.get(asset.asset_id) == asset
    assert characters.get(character.character_id) == character
    assert assets.list(limit=10)[0].tags == ["brand"]


def test_postgres_approval_store_keeps_append_only_latest_decision(tmp_path) -> None:
    database = FakeMetadataDatabase()
    store = PostgresApprovalStore(tmp_path / "approvals", database.connect)
    store.ensure_schema()
    job_id = uuid4()
    approved = store.decide(
        job_id,
        SocialApprovalRequest(platform="wechat", decision="approved", reviewer="editor"),
    )
    rejected = store.decide(
        job_id,
        SocialApprovalRequest(platform="wechat", decision="rejected", reviewer="editor"),
    )

    assert [item.approval_id for item in store.list(job_id)] == [
        approved.approval_id,
        rejected.approval_id,
    ]
    assert store.latest(job_id)["wechat"].decision == "rejected"
    assert len(database.schema_statements) == 2


def test_postgres_audit_store_persists_external_id_without_payloads(tmp_path) -> None:
    database = FakeMetadataDatabase()
    store = PostgresAuditStore(tmp_path / "audit", database.connect)
    store.ensure_schema()
    event = PublishAuditRecord(
        job_id=uuid4(),
        platform="wechat",
        action="publish_succeeded",
        actor="editor",
        dry_run=False,
        message="publisher accepted the draft",
        external_id="external-123",
    )

    store.record(event)
    found = store.list(event.job_id)

    assert found == [event]
    assert found[0].external_id == "external-123"
    assert len(database.schema_statements) == 2
