from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from packages.contracts.models import CreateJobRequest
from packages.storage import (
    ArtifactNotFound,
    FileJobStore,
    FilesystemArtifactStore,
    S3ArtifactStore,
)


class FakeS3Error(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeBody:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.offset = 0
        self.closed = False

    def read(self, size: int | None = None) -> bytes:
        if size is None:
            size = len(self.content) - self.offset
        chunk = self.content[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.content_types: dict[tuple[str, str], str] = {}

    def upload_fileobj(self, handle, bucket: str, key: str, *, ExtraArgs: dict[str, str]) -> None:
        object_id = (bucket, key)
        self.objects[object_id] = handle.read()
        self.content_types[object_id] = ExtraArgs["ContentType"]

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        if (Bucket, Key) not in self.objects:
            raise FakeS3Error("404")
        return {}

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, FakeBody]:
        content = self.objects.get((Bucket, Key))
        if content is None:
            raise FakeS3Error("NoSuchKey")
        return {"Body": FakeBody(content)}


def test_filesystem_artifact_store_keeps_paths_below_staging_root(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    job_id = uuid4()
    path = store.job_dir(job_id) / "story-plan.json"
    path.write_bytes(b'{"ok":true}')

    store.publish(job_id, store.job_dir(job_id))

    assert store.exists(job_id, "story-plan.json")
    assert store.read_bytes(job_id, "story-plan.json") == b'{"ok":true}'
    assert b"".join(store.iter_bytes(job_id, "story-plan.json")) == b'{"ok":true}'
    with pytest.raises(ValueError):
        store.local_path(job_id, "../secret.txt")


def test_s3_artifact_store_publishes_and_streams_generated_files(tmp_path: Path) -> None:
    client = FakeS3()
    store = S3ArtifactStore(client, tmp_path / "staging", bucket="aivs", prefix="studio")
    job_id = uuid4()
    video = store.job_dir(job_id) / "video.mp4"
    video.write_bytes(b"video-bytes")

    store.publish(job_id, store.job_dir(job_id))

    object_id = ("aivs", f"studio/{job_id}/video.mp4")
    assert client.objects[object_id] == b"video-bytes"
    assert client.content_types[object_id] == "video/mp4"
    assert store.exists(job_id, "video.mp4")
    assert store.read_bytes(job_id, "video.mp4") == b"video-bytes"
    assert b"".join(store.iter_bytes(job_id, "video.mp4")) == b"video-bytes"
    assert store.local_path(job_id, "video.mp4") is None

    with pytest.raises(ArtifactNotFound):
        store.read_bytes(job_id, "missing.mp4")


def test_api_streams_s3_artifacts_without_exposing_storage_credentials(tmp_path: Path) -> None:
    job_store = FileJobStore(tmp_path / "state")
    artifact_store = S3ArtifactStore(FakeS3(), tmp_path / "staging", bucket="aivs")
    record = job_store.create(CreateJobRequest(topic="Remote artifact", use_ai=False))
    claimed = job_store.claim_next()
    assert claimed is not None
    artifact_store.job_dir(record.job_id).joinpath("video.mp4").write_bytes(b"remote-video")
    artifact_store.publish(record.job_id, artifact_store.job_dir(record.job_id))
    claimed.status = "succeeded"
    claimed.video_path = "video.mp4"
    job_store.finish(claimed)

    client = TestClient(create_app(store=job_store, artifact_store=artifact_store))
    response = client.get(f"/v1/jobs/{record.job_id}/artifacts/video.mp4")

    assert response.status_code == 200
    assert response.content == b"remote-video"
    assert "attachment" in response.headers["content-disposition"]
    assert "aivs" not in response.headers["content-disposition"]
