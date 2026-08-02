"""Artifact storage adapters for local files and S3-compatible object stores."""

from __future__ import annotations

import mimetypes
import os
import re
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import Any, Protocol
from uuid import UUID


class ArtifactStoreError(RuntimeError):
    """Safe object-storage failure without leaking provider response bodies."""


class ArtifactNotFound(ArtifactStoreError):
    """Raised when a requested generated artifact does not exist."""


class ArtifactStore(Protocol):
    staging_dir: Path

    def job_dir(self, job_id: UUID) -> Path: ...

    def publish(self, job_id: UUID, source_dir: Path) -> None: ...

    def local_path(self, job_id: UUID, artifact_name: str) -> Path | None: ...

    def exists(self, job_id: UUID, artifact_name: str) -> bool: ...

    def read_bytes(self, job_id: UUID, artifact_name: str) -> bytes: ...

    def iter_bytes(self, job_id: UUID, artifact_name: str) -> Iterator[bytes]: ...


_PREFIX_RE = re.compile(r"^[A-Za-z0-9:_./-]{1,200}$")


def _safe_artifact_path(artifact_name: str) -> PurePosixPath:
    normalized = artifact_name.replace("\\", "/").strip()
    path = PurePosixPath(normalized)
    if (
        not normalized
        or path.is_absolute()
        or ".." in path.parts
        or any(part in {"", "."} for part in path.parts)
    ):
        raise ValueError("artifact name must be a relative path without traversal")
    return path


def _safe_under(root: Path, relative: PurePosixPath) -> Path:
    candidate = (root / Path(*relative.parts)).resolve()
    resolved_root = root.resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise ValueError("artifact path escapes the staging root")
    return candidate


def _content_type(artifact_name: str) -> str:
    return mimetypes.guess_type(artifact_name)[0] or "application/octet-stream"


class FilesystemArtifactStore:
    """Keep artifacts below a server-owned directory; publish is a no-op."""

    def __init__(self, root: Path) -> None:
        self.staging_dir = root
        self.staging_dir.mkdir(parents=True, exist_ok=True)

    def job_dir(self, job_id: UUID) -> Path:
        path = self.staging_dir / str(job_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def publish(self, job_id: UUID, source_dir: Path) -> None:
        expected = self.job_dir(job_id).resolve()
        if source_dir.resolve() != expected:
            raise ArtifactStoreError("artifact staging directory is invalid")

    def local_path(self, job_id: UUID, artifact_name: str) -> Path:
        return _safe_under(self.job_dir(job_id), _safe_artifact_path(artifact_name))

    def exists(self, job_id: UUID, artifact_name: str) -> bool:
        return self.local_path(job_id, artifact_name).is_file()

    def read_bytes(self, job_id: UUID, artifact_name: str) -> bytes:
        path = self.local_path(job_id, artifact_name)
        if not path.is_file():
            raise ArtifactNotFound("artifact not found")
        try:
            return path.read_bytes()
        except OSError as exc:
            raise ArtifactStoreError("artifact could not be read") from exc

    def iter_bytes(self, job_id: UUID, artifact_name: str) -> Iterator[bytes]:
        path = self.local_path(job_id, artifact_name)
        if not path.is_file():
            raise ArtifactNotFound("artifact not found")
        try:
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    yield chunk
        except OSError as exc:
            raise ArtifactStoreError("artifact could not be streamed") from exc


class S3ArtifactStore:
    """S3-compatible artifact store, including MinIO and other gateways."""

    def __init__(
        self,
        client: Any,
        root: Path,
        *,
        bucket: str,
        prefix: str = "aivs",
    ) -> None:
        normalized_prefix = prefix.strip("/")
        if not bucket or not _PREFIX_RE.fullmatch(normalized_prefix or "_"):
            raise ValueError("S3 bucket and prefix must be configured safely")
        self.client = client
        self.bucket = bucket
        self.prefix = normalized_prefix
        self.staging_dir = root
        self.staging_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls, root: Path) -> S3ArtifactStore:
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - exercised in deployment
            raise RuntimeError(
                "S3 artifact backend requires the optional dependency: pip install '.[s3]'"
            ) from exc

        bucket = os.getenv("AIVS_S3_BUCKET", "").strip()
        endpoint_url = os.getenv("AIVS_S3_ENDPOINT_URL", "").strip() or None
        region_name = os.getenv("AIVS_S3_REGION", "us-east-1").strip() or "us-east-1"
        access_key = os.getenv("AIVS_S3_ACCESS_KEY_ID", "").strip() or None
        secret_key = os.getenv("AIVS_S3_SECRET_ACCESS_KEY", "").strip() or None
        client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region_name,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        return cls(
            client,
            root / "artifact-staging",
            bucket=bucket,
            prefix=os.getenv("AIVS_S3_PREFIX", "aivs"),
        )

    def job_dir(self, job_id: UUID) -> Path:
        path = self.staging_dir / str(job_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _object_key(self, job_id: UUID, artifact_name: str) -> str:
        relative = _safe_artifact_path(artifact_name)
        parts = [part for part in (self.prefix, str(job_id), relative.as_posix()) if part]
        return "/".join(parts)

    @staticmethod
    def _not_found(error: Exception) -> bool:
        response = getattr(error, "response", {})
        if not isinstance(response, dict):
            return False
        error_data = response.get("Error", {})
        if not isinstance(error_data, dict):
            return False
        return str(error_data.get("Code", "")) in {"404", "NoSuchKey", "NotFound"}

    def publish(self, job_id: UUID, source_dir: Path) -> None:
        expected = self.job_dir(job_id).resolve()
        if source_dir.resolve() != expected:
            raise ArtifactStoreError("artifact staging directory is invalid")
        try:
            files = sorted(path for path in source_dir.rglob("*") if path.is_file())
            for path in files:
                relative = path.relative_to(source_dir).as_posix()
                key = self._object_key(job_id, relative)
                with path.open("rb") as handle:
                    self.client.upload_fileobj(
                        handle,
                        self.bucket,
                        key,
                        ExtraArgs={"ContentType": _content_type(relative)},
                    )
        except (OSError, ValueError) as exc:
            raise ArtifactStoreError("artifact staging could not be uploaded") from exc
        except Exception as exc:  # noqa: BLE001 - hide SDK response details.
            raise ArtifactStoreError("object storage upload failed") from exc

    def local_path(self, job_id: UUID, artifact_name: str) -> None:
        _safe_artifact_path(artifact_name)
        return None

    def exists(self, job_id: UUID, artifact_name: str) -> bool:
        key = self._object_key(job_id, artifact_name)
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception as exc:  # noqa: BLE001 - SDK-specific exception is optional.
            if self._not_found(exc):
                return False
            raise ArtifactStoreError("object storage lookup failed") from exc

    def _get_body(self, job_id: UUID, artifact_name: str) -> Any:
        key = self._object_key(job_id, artifact_name)
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            return response["Body"]
        except Exception as exc:  # noqa: BLE001 - hide SDK response details.
            if self._not_found(exc):
                raise ArtifactNotFound("artifact not found") from exc
            raise ArtifactStoreError("object storage read failed") from exc

    def read_bytes(self, job_id: UUID, artifact_name: str) -> bytes:
        body = self._get_body(job_id, artifact_name)
        try:
            return body.read()
        except Exception as exc:  # noqa: BLE001 - hide SDK response details.
            raise ArtifactStoreError("object storage read failed") from exc
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                close()

    def iter_bytes(self, job_id: UUID, artifact_name: str) -> Iterator[bytes]:
        body = self._get_body(job_id, artifact_name)
        try:
            while chunk := body.read(1024 * 1024):
                yield chunk
        except Exception as exc:  # noqa: BLE001 - hide SDK response details.
            raise ArtifactStoreError("object storage stream failed") from exc
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                close()


def build_artifact_store(root: Path) -> ArtifactStore:
    """Select local or S3/MinIO artifacts from service-owned configuration."""

    backend = os.getenv("AIVS_ARTIFACT_BACKEND", "filesystem").strip().lower()
    if backend in {"filesystem", "file", "local"}:
        return FilesystemArtifactStore(root / "artifacts")
    if backend in {"s3", "minio", "object-storage"}:
        return S3ArtifactStore.from_env(root)
    raise ValueError("AIVS_ARTIFACT_BACKEND must be filesystem or s3")
