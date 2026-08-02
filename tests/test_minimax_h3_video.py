from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from packages.providers import VideoProviderError
from providers.minimax import MiniMaxH3VideoProvider


def test_minimax_h3_submits_native_content_polls_and_downloads(tmp_path: Path) -> None:
    poll_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_count
        if request.method == "POST":
            assert request.headers["authorization"] == "Bearer server-secret"
            assert request.url.path == "/v2/video_generation"
            payload = json.loads(request.content)
            assert payload == {
                "model": "MiniMax-H3",
                "content": [{"type": "text", "text": "a clean city skyline"}],
                "duration": 7,
                "resolution": "768P",
                "ratio": "9:16",
            }
            return httpx.Response(200, json={"task_id": "h3-task-1"})
        if request.url.path == "/v2/query/video_generation/h3-task-1":
            assert request.headers["authorization"] == "Bearer server-secret"
            poll_count += 1
            if poll_count == 1:
                return httpx.Response(200, json={"task": {"status": "running"}})
            return httpx.Response(
                200,
                json={
                    "task": {
                        "status": "succeeded",
                        "content": {"url": "https://filecdn.minimax.chat/h3-task-1.mp4"},
                    }
                },
            )
        assert request.url.host == "filecdn.minimax.chat"
        assert "authorization" not in request.headers
        return httpx.Response(200, content=b"h3-mp4")

    provider = MiniMaxH3VideoProvider(
        base_url="https://api.minimax.io",
        api_key="server-secret",
        poll_interval_seconds=0,
        transport=httpx.MockTransport(handler),
    )
    output = tmp_path / "shot.mp4"

    result = asyncio.run(
        provider.generate(
            prompt="a clean city skyline",
            duration_seconds=7,
            output_path=output,
        )
    )

    assert result == output
    assert output.read_bytes() == b"h3-mp4"
    assert poll_count == 2


def test_minimax_h3_sends_reference_image_urls(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            payload = json.loads(request.content)
            assert payload["content"][1] == {
                "type": "image_url",
                "image_url": {"url": "https://cdn.example.test/character.png"},
                "role": "reference_image",
            }
            return httpx.Response(200, json={"task_id": "h3-task-2"})
        if request.url.path.endswith("h3-task-2"):
            return httpx.Response(
                200,
                json={
                    "task": {
                        "status": "succeeded",
                        "content": {"url": "https://filecdn.minimax.chat/h3-task-2.mp4"},
                    }
                },
            )
        return httpx.Response(200, content=b"reference-mp4")

    provider = MiniMaxH3VideoProvider(
        base_url="https://api.minimax.io",
        api_key="server-secret",
        poll_interval_seconds=0,
        transport=httpx.MockTransport(handler),
    )
    output = asyncio.run(
        provider.generate(
            prompt="keep the character consistent",
            duration_seconds=5,
            output_path=tmp_path / "reference.mp4",
            reference_images=(tmp_path / "character.png",),
            reference_image_urls=("https://cdn.example.test/character.png",),
        )
    )
    assert output.read_bytes() == b"reference-mp4"


def test_minimax_h3_requires_public_urls_for_local_reference_assets(tmp_path: Path) -> None:
    provider = MiniMaxH3VideoProvider(
        base_url="https://api.minimax.io",
        api_key="server-secret",
    )

    with pytest.raises(VideoProviderError, match="public URLs") as error:
        asyncio.run(
            provider.generate(
                prompt="reference",
                duration_seconds=5,
                output_path=tmp_path / "reference.mp4",
                reference_images=(tmp_path / "character.png",),
            )
        )
    assert error.value.code == "reference_url_required"
    assert error.value.retryable is False


@pytest.mark.parametrize("duration", [3, 16])
def test_minimax_h3_rejects_out_of_range_duration(tmp_path: Path, duration: int) -> None:
    provider = MiniMaxH3VideoProvider(
        base_url="https://api.minimax.io",
        api_key="server-secret",
    )

    with pytest.raises(VideoProviderError) as error:
        asyncio.run(
            provider.generate(
                prompt="invalid duration",
                duration_seconds=duration,
                output_path=tmp_path / "invalid.mp4",
            )
        )
    assert error.value.code == "invalid_duration"


def test_minimax_h3_rejects_adaptive_ratio_without_reference_image(tmp_path: Path) -> None:
    provider = MiniMaxH3VideoProvider(
        base_url="https://api.minimax.io",
        api_key="server-secret",
        ratio="adaptive",
    )

    with pytest.raises(VideoProviderError) as error:
        asyncio.run(
            provider.generate(
                prompt="adaptive framing",
                duration_seconds=5,
                output_path=tmp_path / "adaptive.mp4",
            )
        )
    assert error.value.code == "invalid_ratio"


def test_minimax_h3_maps_terminal_failure_without_leaking_response_body(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"task_id": "h3-failed"})
        return httpx.Response(
            200,
            json={
                "task": {
                    "status": "failed",
                    "error": {"message": "secret-provider-detail"},
                }
            },
        )

    provider = MiniMaxH3VideoProvider(
        base_url="https://api.minimax.io",
        api_key="server-secret",
        poll_interval_seconds=0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(VideoProviderError, match="status failed") as error:
        asyncio.run(
            provider.generate(
                prompt="failure",
                duration_seconds=5,
                output_path=tmp_path / "failed.mp4",
            )
        )
    assert "secret-provider-detail" not in str(error.value)
    assert error.value.code == "provider_job_failed"
    assert error.value.retryable is False
