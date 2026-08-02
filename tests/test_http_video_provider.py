import asyncio

import httpx
import pytest

from packages.providers import VideoProviderError
from packages.providers.http_video import HTTPVideoProvider


def test_generic_http_video_provider_submits_polls_and_downloads(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"id": "job-1"})
        if request.url.path == "/videos/job-1":
            return httpx.Response(
                200, json={"status": "succeeded", "video_url": "https://provider.test/video.mp4"}
            )
        return httpx.Response(200, content=b"synthetic-mp4")

    provider = HTTPVideoProvider(
        provider_id="synthetic-http",
        base_url="https://provider.test",
        api_key="server-secret",
        model="synthetic-video",
        poll_interval_seconds=0,
        transport=httpx.MockTransport(handler),
    )
    output = tmp_path / "video.mp4"

    result = asyncio.run(
        provider.generate(
            prompt="synthetic prompt",
            duration_seconds=15,
            output_path=output,
        )
    )

    assert result == output
    assert output.read_bytes() == b"synthetic-mp4"


def test_generic_http_video_provider_rejects_untrusted_download_url(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        return httpx.Response(200, json={"video_url": "https://evil.test/video.mp4"})

    provider = HTTPVideoProvider(
        provider_id="synthetic-http",
        base_url="https://provider.test",
        api_key="server-secret",
        model="synthetic-video",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(VideoProviderError, match="allow-list") as error:
        asyncio.run(
            provider.generate(
                prompt="synthetic prompt",
                duration_seconds=15,
                output_path=tmp_path / "video.mp4",
            )
        )
    assert error.value.code == "unsafe_download_url"
    assert error.value.retryable is False
