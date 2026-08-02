"""PostgreSQL-backed reusable asset and character catalogs.

Binary asset files still live in the server-owned catalog directory (or can be
copied into an object store by a future adapter). PostgreSQL stores the
metadata and reference relationships so multiple API/worker processes share a
single catalog without changing the provider-neutral application contract.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from packages.contracts.models import (
    AssetRecord,
    CharacterRecord,
    CreateCharacterRequest,
)
from packages.storage import PostgresSession, postgres_connect_from_env

from .catalog import AssetCatalog, CatalogNotFound, CharacterCatalog

_ASSET_COLUMNS = (
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
_CHARACTER_COLUMNS = (
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

CATALOG_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS aivs_assets (
        asset_id UUID PRIMARY KEY,
        name TEXT NOT NULL,
        kind TEXT NOT NULL,
        storage_key TEXT,
        mime_type TEXT NOT NULL,
        tags JSONB NOT NULL,
        size_bytes BIGINT NOT NULL CHECK (size_bytes >= 0),
        sha256 TEXT,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS aivs_assets_created_idx ON aivs_assets (created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS aivs_characters (
        character_id UUID PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL,
        prompt TEXT NOT NULL,
        voice TEXT NOT NULL,
        language TEXT NOT NULL,
        reference_asset_ids JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS aivs_characters_created_idx
    ON aivs_characters (created_at DESC)
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


def _as_json_list(value: Any) -> list[Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return list(value or [])


class PostgresAssetCatalog(AssetCatalog):
    """Metadata catalog with the same interface as :class:`AssetCatalog`."""

    def __init__(self, root: Path, connect: Callable[[], Any]) -> None:
        super().__init__(root)
        self._connect = connect

    @classmethod
    def from_env(cls, root: Path) -> PostgresAssetCatalog:
        catalog = cls(root, postgres_connect_from_env())
        catalog.ensure_schema()
        return catalog

    def _session(self) -> PostgresSession:
        return PostgresSession(self._connect)

    def ensure_schema(self) -> None:
        with self._session() as (_connection, cursor):
            for statement in CATALOG_SCHEMA_STATEMENTS:
                cursor.execute(statement)

    @staticmethod
    def _row_to_record(row: Any) -> AssetRecord:
        values = row if isinstance(row, dict) else dict(zip(_ASSET_COLUMNS, row, strict=True))
        return AssetRecord(
            asset_id=_as_uuid(values["asset_id"]),
            name=values["name"],
            kind=values["kind"],
            storage_key=values["storage_key"],
            mime_type=values["mime_type"],
            tags=[str(item) for item in _as_json_list(values["tags"])],
            size_bytes=int(values["size_bytes"]),
            sha256=values["sha256"],
            created_at=_as_datetime(values["created_at"]),
            updated_at=_as_datetime(values["updated_at"]),
        )

    def get(self, asset_id: UUID) -> AssetRecord | None:
        with self._session() as (_connection, cursor):
            cursor.execute(
                f"SELECT {', '.join(_ASSET_COLUMNS)} FROM aivs_assets WHERE asset_id = %s",
                (asset_id,),
            )
            row = cursor.fetchone()
            return None if row is None else self._row_to_record(row)

    def _save(self, record: AssetRecord) -> AssetRecord:
        record.updated_at = datetime.now(UTC)
        with self._session() as (_connection, cursor):
            cursor.execute(
                """
                INSERT INTO aivs_assets
                    (asset_id, name, kind, storage_key, mime_type, tags, size_bytes,
                     sha256, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, CAST(%s AS jsonb), %s, %s, %s, %s)
                ON CONFLICT (asset_id) DO UPDATE SET
                    name = EXCLUDED.name, kind = EXCLUDED.kind,
                    storage_key = EXCLUDED.storage_key, mime_type = EXCLUDED.mime_type,
                    tags = EXCLUDED.tags, size_bytes = EXCLUDED.size_bytes,
                    sha256 = EXCLUDED.sha256, updated_at = EXCLUDED.updated_at
                """,
                (
                    record.asset_id,
                    record.name,
                    record.kind,
                    record.storage_key,
                    record.mime_type,
                    json.dumps(record.tags),
                    record.size_bytes,
                    record.sha256,
                    record.created_at,
                    record.updated_at,
                ),
            )
        return record

    def list(self, *, limit: int = 100) -> list[AssetRecord]:
        with self._session() as (_connection, cursor):
            cursor.execute(
                f"SELECT {', '.join(_ASSET_COLUMNS)} FROM aivs_assets "
                "ORDER BY created_at DESC LIMIT %s",
                (limit,),
            )
            return [self._row_to_record(row) for row in cursor.fetchall()]


class PostgresCharacterCatalog(CharacterCatalog):
    """Character metadata catalog backed by PostgreSQL."""

    def __init__(
        self,
        root: Path,
        assets: PostgresAssetCatalog,
        connect: Callable[[], Any],
    ) -> None:
        super().__init__(root, assets)
        self._connect = connect

    @classmethod
    def from_env(cls, root: Path, assets: PostgresAssetCatalog) -> PostgresCharacterCatalog:
        catalog = cls(root, assets, assets._connect)
        catalog.ensure_schema()
        return catalog

    def _session(self) -> PostgresSession:
        return PostgresSession(self._connect)

    def ensure_schema(self) -> None:
        with self._session() as (_connection, cursor):
            for statement in CATALOG_SCHEMA_STATEMENTS:
                cursor.execute(statement)

    @staticmethod
    def _row_to_record(row: Any) -> CharacterRecord:
        values = row if isinstance(row, dict) else dict(zip(_CHARACTER_COLUMNS, row, strict=True))
        return CharacterRecord(
            character_id=_as_uuid(values["character_id"]),
            name=values["name"],
            description=values["description"],
            prompt=values["prompt"],
            voice=values["voice"],
            language=values["language"],
            reference_asset_ids=[
                _as_uuid(item) for item in _as_json_list(values["reference_asset_ids"])
            ],
            created_at=_as_datetime(values["created_at"]),
            updated_at=_as_datetime(values["updated_at"]),
        )

    def get(self, character_id: UUID) -> CharacterRecord | None:
        with self._session() as (_connection, cursor):
            cursor.execute(
                f"SELECT {', '.join(_CHARACTER_COLUMNS)} FROM aivs_characters "
                "WHERE character_id = %s",
                (character_id,),
            )
            row = cursor.fetchone()
            return None if row is None else self._row_to_record(row)

    def create(self, request: CreateCharacterRequest) -> CharacterRecord:
        for asset_id in request.reference_asset_ids:
            if self.assets.get(asset_id) is None:
                raise CatalogNotFound(f"asset is not registered: {asset_id}")
        record = CharacterRecord(**request.model_dump())
        record.updated_at = datetime.now(UTC)
        with self._session() as (_connection, cursor):
            cursor.execute(
                """
                INSERT INTO aivs_characters
                    (character_id, name, description, prompt, voice, language,
                     reference_asset_ids, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, CAST(%s AS jsonb), %s, %s)
                ON CONFLICT (character_id) DO UPDATE SET
                    name = EXCLUDED.name, description = EXCLUDED.description,
                    prompt = EXCLUDED.prompt, voice = EXCLUDED.voice,
                    language = EXCLUDED.language,
                    reference_asset_ids = EXCLUDED.reference_asset_ids,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    record.character_id,
                    record.name,
                    record.description,
                    record.prompt,
                    record.voice,
                    record.language,
                    json.dumps([str(item) for item in record.reference_asset_ids]),
                    record.created_at,
                    record.updated_at,
                ),
            )
        return record

    def list(self, *, limit: int = 100) -> list[CharacterRecord]:
        with self._session() as (_connection, cursor):
            cursor.execute(
                f"SELECT {', '.join(_CHARACTER_COLUMNS)} FROM aivs_characters "
                "ORDER BY created_at DESC LIMIT %s",
                (limit,),
            )
            return [self._row_to_record(row) for row in cursor.fetchall()]


def _configured_backend() -> str:
    configured = os.getenv("AIVS_CATALOG_BACKEND", "").strip().lower()
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


def build_catalogs(root: Path) -> tuple[AssetCatalog, CharacterCatalog]:
    """Build local or PostgreSQL metadata catalogs from server configuration."""

    backend = _configured_backend()
    if backend in {"filesystem", "file", "local"}:
        assets = AssetCatalog(root / "assets")
        return assets, CharacterCatalog(root / "characters", assets)
    if backend in {"postgres", "postgresql"}:
        connect = postgres_connect_from_env()
        assets = PostgresAssetCatalog(root / "assets", connect)
        assets.ensure_schema()
        characters = PostgresCharacterCatalog(root / "characters", assets, connect)
        characters.ensure_schema()
        return assets, characters
    raise ValueError("AIVS_CATALOG_BACKEND must be filesystem or postgres")
