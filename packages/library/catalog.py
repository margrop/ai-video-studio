"""Small filesystem catalogs for reusable content assets.

Catalog records are JSON and binary files are kept below a server-owned root.
The public API can create metadata records; local operators can use
``AssetCatalog.import_file`` to copy a source file into that root without
letting an HTTP request choose an arbitrary filesystem path.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from packages.contracts.models import (
    AssetRecord,
    CharacterRecord,
    CreateAssetRequest,
    CreateCharacterRequest,
    TemplateSummary,
)


class CatalogNotFound(KeyError):
    """Raised when a server-owned catalog record does not exist."""


class _JsonStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

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

    @staticmethod
    def _atomic_write_bytes(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            Path(temporary_name).replace(path)
        finally:
            temporary = Path(temporary_name)
            if temporary.exists():
                temporary.unlink()


class AssetCatalog(_JsonStore):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.records_dir = root / "records"
        self.files_dir = root / "files"
        self.records_dir.mkdir(parents=True, exist_ok=True)
        self.files_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, asset_id: UUID) -> Path:
        return self.records_dir / f"{asset_id}.json"

    def get(self, asset_id: UUID) -> AssetRecord | None:
        path = self._path(asset_id)
        if not path.exists():
            return None
        return AssetRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def local_path(self, asset_id: UUID) -> Path | None:
        """Return a server-owned imported file path, never a user path."""

        record = self.get(asset_id)
        if record is None or not record.storage_key:
            return None
        candidate = (self.files_dir / record.storage_key).resolve()
        if self.files_dir.resolve() not in candidate.parents or not candidate.is_file():
            return None
        return candidate

    def write_bytes(
        self,
        asset_id: UUID,
        content: bytes,
        *,
        mime_type: str | None = None,
    ) -> AssetRecord:
        """Store bytes at the record-owned key and update integrity metadata."""

        record = self.get(asset_id)
        if record is None:
            raise CatalogNotFound(f"asset is not registered: {asset_id}")
        if record.storage_key is None:
            record.storage_key = f"{record.kind}/{record.asset_id}"
        destination = (self.files_dir / record.storage_key).resolve()
        if self.files_dir.resolve() not in destination.parents:
            raise ValueError("asset destination escapes the asset root")
        self._atomic_write_bytes(destination, content)
        record.size_bytes = len(content)
        record.sha256 = hashlib.sha256(content).hexdigest()
        if mime_type:
            record.mime_type = mime_type[:100]
        return self._save(record)

    def create(self, request: CreateAssetRequest) -> AssetRecord:
        record = AssetRecord(**request.model_dump())
        self._save(record)
        return record

    def import_file(self, source: Path, request: CreateAssetRequest) -> AssetRecord:
        """Import a local file using a server-side/operator-controlled path."""

        source = source.expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        storage_key = request.storage_key or f"{request.kind}/{source.name}"
        destination = (self.files_dir / storage_key).resolve()
        if self.files_dir.resolve() not in destination.parents:
            raise ValueError("asset destination escapes the asset root")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        digest = hashlib.sha256()
        size = 0
        with destination.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
        record = AssetRecord(
            **request.model_dump(exclude={"storage_key"}),
            storage_key=storage_key,
            size_bytes=size,
            sha256=digest.hexdigest(),
        )
        self._save(record)
        return record

    def _save(self, record: AssetRecord) -> AssetRecord:
        record.updated_at = datetime.now(UTC)
        self._atomic_write(self._path(record.asset_id), record.model_dump_json(indent=2))
        return record

    def list(self, *, limit: int = 100) -> list[AssetRecord]:
        records: list[AssetRecord] = []
        for path in self.records_dir.glob("*.json"):
            try:
                records.append(AssetRecord.model_validate_json(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        records.sort(key=lambda item: item.created_at, reverse=True)
        return records[:limit]


class CharacterCatalog(_JsonStore):
    def __init__(self, root: Path, assets: AssetCatalog) -> None:
        super().__init__(root)
        self.assets = assets

    def _path(self, character_id: UUID) -> Path:
        return self.root / f"{character_id}.json"

    def get(self, character_id: UUID) -> CharacterRecord | None:
        path = self._path(character_id)
        if not path.exists():
            return None
        return CharacterRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def create(self, request: CreateCharacterRequest) -> CharacterRecord:
        for asset_id in request.reference_asset_ids:
            if self.assets.get(asset_id) is None:
                raise CatalogNotFound(f"asset is not registered: {asset_id}")
        record = CharacterRecord(**request.model_dump())
        self._atomic_write(self._path(record.character_id), record.model_dump_json(indent=2))
        return record

    def list(self, *, limit: int = 100) -> list[CharacterRecord]:
        records: list[CharacterRecord] = []
        for path in self.root.glob("*.json"):
            try:
                records.append(
                    CharacterRecord.model_validate_json(path.read_text(encoding="utf-8"))
                )
            except (OSError, ValueError):
                continue
        records.sort(key=lambda item: item.created_at, reverse=True)
        return records[:limit]


class TemplateCatalog:
    def __init__(self, root: Path) -> None:
        self.root = root

    @staticmethod
    def _read(path: Path) -> dict[str, object]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"template is invalid: {path.name}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"template is invalid: {path.name}")
        return data

    def _load(self, template_id: str) -> dict[str, object]:
        if not template_id or Path(template_id).name != template_id:
            raise CatalogNotFound(f"template is not registered: {template_id}")
        direct_path = self.root / f"{template_id}.json"
        candidates = [direct_path] if direct_path.is_file() else sorted(self.root.glob("*.json"))
        for path in candidates:
            try:
                data = self._read(path)
            except ValueError:
                continue
            if str(data.get("template_id", path.stem)) == template_id:
                return data
        raise CatalogNotFound(f"template is not registered: {template_id}")

    @staticmethod
    def _summary(data: dict[str, object], fallback_id: str) -> TemplateSummary:
        review = data.get("review", {})
        if not isinstance(review, dict):
            review = {}
        return TemplateSummary(
            template_id=str(data.get("template_id", fallback_id)),
            title_style=str(data.get("title_style", "")),
            target_duration_seconds=int(data.get("target_duration_seconds", 60)),
            language=str(data.get("language", "zh-CN")),
            voice=str(data.get("voice", "neutral")),
            requires_human_approval_before_publish=bool(
                review.get("requires_human_approval_before_publish", True)
            ),
            allow_external_posting=bool(review.get("allow_external_posting", False)),
        )

    def get(self, template_id: str) -> TemplateSummary:
        return self._summary(self._load(template_id), template_id)

    def list(self) -> list[TemplateSummary]:
        templates: list[TemplateSummary] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                data = self._read(path)
                template_id = str(data.get("template_id", path.stem))
                templates.append(self._summary(data, template_id))
            except ValueError:
                continue
        return templates

    def prompt_config(self, template_id: str) -> dict[str, str]:
        data = self._load(template_id)
        raw_prompt = data.get("prompt", {})
        if not isinstance(raw_prompt, dict):
            return {}
        return {
            key: str(raw_prompt[key])
            for key in ("base", "camera", "lighting", "negative")
            if key in raw_prompt
        }
