from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from packages.providers import VideoProviderError
from providers.volcengine import VolcengineAgentPlanVideoProvider


def test_agent_plan_submits_polls_and_downloads_without_forwarding_api_key(
    tmp_path: Path,
) -> None:
    poll_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_count
        if request.method == "POST":
            assert request.headers["authorization"] == "Bearer agent-secret"
            assert request.url.path == "/api/plan/v3/contents/generations/tasks"
            payload = json.loads(request.content)
            assert payload == {
                "model": "doubao-seedance-2.0",
                "content": [{"type": "text", "text": "a clean city skyline"}],
                "generate_audio": False,
                "ratio": "9:16",
                "duration": 7,
                "watermark": False,
                "resolution": "720p",
            }
            return httpx.Response(200, json={"id": "cgt-task-1"})
        if request.url.path == "/api/plan/v3/contents/generations/tasks/cgt-task-1":
            assert request.headers["authorization"] == "Bearer agent-secret"
            poll_count += 1
            if poll_count == 1:
                return httpx.Response(200, json={"status": "running"})
            return httpx.Response(
                200,
                json={
                    "status": "succeeded",
                    "content": {
                        "video_url": (
                            "https://ark-content-generation-cn-beijing.tos-cn-beijing.volces.com/"
                            "cgt-task-1.mp4"
                        )
                    },
                },
            )
        assert request.url.host == "ark-content-generation-cn-beijing.tos-cn-beijing.volces.com"
        assert "authorization" not in request.headers
        return httpx.Response(200, content=b"ark-mp4")

    provider = VolcengineAgentPlanVideoProvider(
        base_url="https://ark.cn-beijing.volces.com/api/plan/v3",
        api_key="agent-secret",
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
    assert output.read_bytes() == b"ark-mp4"
    assert poll_count == 2


def test_agent_plan_supports_reference_images_and_optional_role(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            payload = json.loads(request.content)
            assert payload["content"][1] == {
                "type": "image_url",
                "image_url": {"url": "https://cdn.example.test/character.png"},
                "role": "reference_image",
            }
            return httpx.Response(200, json={"id": "cgt-task-2"})
        if request.url.path.endswith("cgt-task-2"):
            return httpx.Response(
                200,
                json={
                    "status": "succeeded",
                    "content": {
                        "video_url": "https://ark-project.tos-cn-beijing.volces.com/cgt-task-2.mp4"
                    },
                },
            )
        return httpx.Response(200, content=b"reference-mp4")

    provider = VolcengineAgentPlanVideoProvider(
        base_url="https://ark.cn-beijing.volces.com/api/plan/v3",
        api_key="agent-secret",
        reference_role="reference_image",
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


def test_agent_plan_requires_public_urls_for_local_reference_assets(tmp_path: Path) -> None:
    provider = VolcengineAgentPlanVideoProvider(
        base_url="https://ark.cn-beijing.volces.com/api/plan/v3",
        api_key="agent-secret",
    )

    with pytest.raises(VideoProviderError, match="reference assets") as error:
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
def test_agent_plan_rejects_out_of_range_duration(tmp_path: Path, duration: int) -> None:
    provider = VolcengineAgentPlanVideoProvider(
        base_url="https://ark.cn-beijing.volces.com/api/plan/v3",
        api_key="agent-secret",
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


def test_agent_plan_maps_terminal_failure_without_leaking_response_body(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"id": "cgt-failed"})
        return httpx.Response(
            200,
            json={
                "status": "failed",
                "error": {"message": "secret-provider-detail"},
            },
        )

    provider = VolcengineAgentPlanVideoProvider(
        base_url="https://ark.cn-beijing.volces.com/api/plan/v3",
        api_key="agent-secret",
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
