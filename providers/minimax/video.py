"""Native MiniMax H3 video provider.

MiniMax H3 does not use the generic OpenAI video contract. It accepts a
multimodal ``content`` array, creates an asynchronous task, exposes a native
query endpoint, and returns a temporary download URL in ``task.content.url``.
This adapter keeps those details at the vendor boundary while the workflow
continues to depend on ``VideoProvider``.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from packages.providers import VideoProviderError
from packages.providers.http_video import HTTPVideoProvider


class MiniMaxH3VideoProvider(HTTPVideoProvider):
    """Generate one 4–15 second Shot through MiniMax's native H3 API."""

    provider_id = "minimax-video"
    allowed_ratios = frozenset({"adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"})
    capabilities = (
        "async-generation",
        "h3-native-api",
        "multimodal-reference-images",
        "remote-download",
        "shot-generation",
        "text-to-video",
    )

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str = "MiniMax-H3",
        resolution: str = "768P",
        ratio: str = "9:16",
        poll_interval_seconds: float = 10.0,
        max_wait_seconds: float = 900.0,
        allowed_download_hosts: tuple[str, ...] = (),
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            provider_id=self.provider_id,
            base_url=base_url,
            api_key=api_key,
            model=model,
            submit_path="/v2/video_generation",
            poll_path_template="/v2/query/video_generation/{job_id}",
            poll_interval_seconds=poll_interval_seconds,
            max_wait_seconds=max_wait_seconds,
            allowed_download_hosts=("filecdn.minimax.chat", *allowed_download_hosts),
            transport=transport,
        )
        self.resolution = resolution.upper()
        self.ratio = ratio.strip()

    @classmethod
    def from_env(cls) -> MiniMaxH3VideoProvider:
        def env(name: str, default: str = "") -> str:
            return os.getenv(
                f"AIVS_MINIMAX_VIDEO_{name}",
                os.getenv(f"AIVS_VIDEO_{name}", default),
            )

        def env_float(name: str, default: float, minimum: float, maximum: float) -> float:
            try:
                value = float(env(name, str(default)))
            except ValueError:
                return default
            return value if minimum <= value <= maximum else default

        raw_hosts = env("ALLOWED_DOWNLOAD_HOSTS")
        allowed_hosts = tuple(host.strip() for host in raw_hosts.split(",") if host.strip())
        return cls(
            base_url=env("BASE_URL", "https://api.minimax.io"),
            api_key=env("API_KEY"),
            model=env("MODEL", "MiniMax-H3"),
            resolution=env("RESOLUTION", "768P"),
            ratio=env("RATIO", "9:16"),
            poll_interval_seconds=env_float("POLL_INTERVAL_SECONDS", 10.0, 0, 60),
            max_wait_seconds=env_float("MAX_WAIT_SECONDS", 900.0, 5, 3_600),
            allowed_download_hosts=allowed_hosts,
        )

    @staticmethod
    def _error_for_status(status_code: int, phase: str) -> VideoProviderError:
        if status_code in {401, 403}:
            return VideoProviderError(
                "provider_auth_error",
                f"MiniMax H3 {phase} authorization failed",
                retryable=False,
            )
        if status_code == 402:
            return VideoProviderError(
                "provider_insufficient_balance",
                f"MiniMax H3 {phase} rejected because the account has insufficient balance",
                retryable=False,
            )
        if status_code == 422:
            return VideoProviderError(
                "provider_content_rejected",
                f"MiniMax H3 {phase} rejected the content",
                retryable=False,
            )
        if status_code == 429:
            return VideoProviderError(
                "provider_rate_limited",
                f"MiniMax H3 {phase} was rate limited",
                retryable=True,
            )
        if status_code >= 500:
            return VideoProviderError(
                "provider_unavailable",
                f"MiniMax H3 {phase} is temporarily unavailable",
                retryable=True,
            )
        return VideoProviderError(
            "provider_request_rejected",
            f"MiniMax H3 {phase} request was rejected",
            retryable=False,
        )

    async def _request_json(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        phase: str,
        **kwargs: object,
    ) -> dict[str, object]:
        try:
            response = await client.request(method, url, **kwargs)
        except httpx.TimeoutException as exc:
            raise VideoProviderError(
                "provider_timeout", f"MiniMax H3 {phase} request timed out"
            ) from exc
        except httpx.HTTPError as exc:
            raise VideoProviderError(
                "provider_unavailable", f"MiniMax H3 {phase} request failed"
            ) from exc

        if response.is_error:
            raise self._error_for_status(response.status_code, phase)
        try:
            data = response.json()
        except ValueError as exc:
            raise VideoProviderError(
                "invalid_provider_response",
                f"MiniMax H3 {phase} response was not JSON",
                retryable=False,
            ) from exc
        if not isinstance(data, dict):
            raise VideoProviderError(
                "invalid_provider_response",
                f"MiniMax H3 {phase} response was not an object",
                retryable=False,
            )
        if isinstance(data.get("error"), dict):
            error_type = str(data["error"].get("type", "provider_error"))
            if "rate_limit" in error_type:
                raise VideoProviderError(
                    "provider_rate_limited", "MiniMax H3 request was rate limited"
                )
            raise VideoProviderError(
                "provider_request_rejected",
                f"MiniMax H3 returned {error_type}",
                retryable=False,
            )
        return data

    @staticmethod
    def _validate_reference_url(candidate: str) -> str:
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise VideoProviderError(
                "invalid_reference_url",
                "MiniMax H3 reference inputs must use public HTTP(S) URLs",
                retryable=False,
            )
        return candidate

    @staticmethod
    def _task(data: dict[str, object]) -> dict[str, object]:
        task = data.get("task")
        if not isinstance(task, dict):
            raise VideoProviderError(
                "invalid_provider_response",
                "MiniMax H3 query response did not contain a task",
                retryable=False,
            )
        return task

    async def generate(
        self,
        *,
        prompt: str,
        duration_seconds: int,
        output_path: Path,
        reference_images: tuple[Path, ...] = (),
        reference_image_urls: tuple[str, ...] = (),
    ) -> Path:
        if not self.base_url or not self.api_key or not self.model:
            raise VideoProviderError(
                "provider_not_configured",
                "MiniMax H3 video provider is not fully configured",
                retryable=False,
            )
        if not prompt.strip():
            raise VideoProviderError(
                "invalid_prompt", "MiniMax H3 prompt cannot be empty", retryable=False
            )
        if duration_seconds < 4 or duration_seconds > 15:
            raise VideoProviderError(
                "invalid_duration",
                "MiniMax H3 duration must be an integer between 4 and 15 seconds",
                retryable=False,
            )
        if self.resolution not in {"768P", "2K"}:
            raise VideoProviderError(
                "invalid_resolution",
                "MiniMax H3 resolution must be 768P or 2K",
                retryable=False,
            )
        if self.ratio not in self.allowed_ratios:
            raise VideoProviderError(
                "invalid_ratio",
                "MiniMax H3 ratio must be adaptive, 21:9, 16:9, 4:3, 1:1, 3:4 or 9:16",
                retryable=False,
            )
        if self.ratio == "adaptive" and not reference_image_urls:
            raise VideoProviderError(
                "invalid_ratio",
                "MiniMax H3 adaptive ratio requires a reference image",
                retryable=False,
            )
        if reference_images and not reference_image_urls:
            raise VideoProviderError(
                "reference_url_required",
                "MiniMax H3 reference assets require public URLs; configure the asset URL template",
                retryable=False,
            )
        if len(reference_image_urls) > 9:
            raise VideoProviderError(
                "too_many_reference_images",
                "MiniMax H3 accepts at most 9 reference images",
                retryable=False,
            )

        content: list[dict[str, object]] = [{"type": "text", "text": prompt.strip()}]
        for candidate in reference_image_urls:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": self._validate_reference_url(candidate)},
                    "role": "reference_image",
                }
            )
        payload = {
            "model": self.model,
            "content": content,
            "duration": duration_seconds,
            "resolution": self.resolution,
            "ratio": self.ratio,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        deadline = time.monotonic() + self.max_wait_seconds
        timeout = httpx.Timeout(60.0, connect=15.0)
        async with httpx.AsyncClient(timeout=timeout, transport=self.transport) as client:
            submitted = await self._request_json(
                client,
                "POST",
                self._url("/v2/video_generation"),
                phase="submit",
                headers=headers,
                json=payload,
            )
            task_id = submitted.get("task_id")
            if not isinstance(task_id, (str, int)) or not str(task_id):
                raise VideoProviderError(
                    "invalid_provider_response",
                    "MiniMax H3 submit response did not contain a task ID",
                    retryable=False,
                )

            download_url: str | None = None
            while time.monotonic() < deadline:
                status_data = await self._request_json(
                    client,
                    "GET",
                    self._url(f"/v2/query/video_generation/{task_id}"),
                    phase="poll",
                    headers=headers,
                )
                task = self._task(status_data)
                state = str(task.get("status", "")).lower()
                if state == "succeeded":
                    content_data = task.get("content")
                    if isinstance(content_data, dict):
                        candidate = content_data.get("url")
                        if isinstance(candidate, str) and candidate:
                            download_url = candidate
                    if download_url is None:
                        raise VideoProviderError(
                            "invalid_provider_response",
                            "MiniMax H3 succeeded without a video URL",
                            retryable=False,
                        )
                    break
                if state in {"failed", "cancelled", "canceled", "expired"}:
                    raise VideoProviderError(
                        "provider_job_failed",
                        f"MiniMax H3 task ended with status {state}",
                        retryable=False,
                    )
                await asyncio.sleep(
                    min(self.poll_interval_seconds, max(0, deadline - time.monotonic()))
                )

            if download_url is None:
                raise VideoProviderError("provider_timeout", "MiniMax H3 video task timed out")
            safe_url = self._safe_download_url(download_url)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = output_path.with_suffix(f"{output_path.suffix}.download")
            try:
                # The returned URL is signed/CDN-owned; do not send the API key.
                async with client.stream("GET", safe_url) as response:
                    response.raise_for_status()
                    with temporary_path.open("wb") as handle:
                        async for chunk in response.aiter_bytes():
                            handle.write(chunk)
                temporary_path.replace(output_path)
            except httpx.TimeoutException as exc:
                temporary_path.unlink(missing_ok=True)
                raise VideoProviderError(
                    "provider_timeout", "MiniMax H3 video download timed out"
                ) from exc
            except (httpx.HTTPError, OSError) as exc:
                temporary_path.unlink(missing_ok=True)
                raise VideoProviderError(
                    "provider_download_failed", "MiniMax H3 video download failed"
                ) from exc
        return output_path


__all__ = ["MiniMaxH3VideoProvider"]
