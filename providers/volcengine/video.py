"""Native Volcengine Ark Agent Plan video provider.

Ark Agent Plan exposes Seedance through the native asynchronous content
generation task API. It is deliberately kept outside the generic HTTP video
adapter because the request uses a multimodal ``content`` array and the
successful result is returned as ``content.video_url``.
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


class VolcengineAgentPlanVideoProvider(HTTPVideoProvider):
    """Generate one Story Plan Shot through Ark Agent Plan Seedance."""

    provider_id = "volcengine-agentplan-video"
    allowed_ratios = frozenset({"adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"})
    allowed_resolutions = frozenset({"480p", "720p", "1080p", "4k"})
    allowed_reference_roles = frozenset({"", "first_frame", "last_frame", "reference_image"})
    capabilities = (
        "agent-plan-native-api",
        "async-generation",
        "multimodal-reference-images",
        "remote-download",
        "shot-generation",
        "text-to-video",
    )
    default_download_hosts = (
        "ark-content-generation-cn-beijing.tos-cn-beijing.volces.com",
        "ark-project.tos-cn-beijing.volces.com",
    )

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str = "doubao-seedance-2.0",
        resolution: str = "720p",
        ratio: str = "9:16",
        generate_audio: bool = False,
        watermark: bool = False,
        reference_role: str = "",
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
            submit_path="/contents/generations/tasks",
            poll_path_template="/contents/generations/tasks/{job_id}",
            poll_interval_seconds=poll_interval_seconds,
            max_wait_seconds=max_wait_seconds,
            allowed_download_hosts=(*self.default_download_hosts, *allowed_download_hosts),
            transport=transport,
        )
        self.resolution = resolution.strip().lower()
        self.ratio = ratio.strip()
        self.generate_audio = generate_audio
        self.watermark = watermark
        self.reference_role = reference_role.strip().lower()

    @classmethod
    def from_env(cls) -> VolcengineAgentPlanVideoProvider:
        def env(name: str, default: str = "") -> str:
            return os.getenv(
                f"AIVS_VOLCENGINE_VIDEO_{name}",
                os.getenv(f"AIVS_VIDEO_{name}", default),
            )

        def env_float(name: str, default: float, minimum: float, maximum: float) -> float:
            try:
                value = float(env(name, str(default)))
            except ValueError:
                return default
            return value if minimum <= value <= maximum else default

        def env_bool(name: str, default: bool) -> bool:
            value = env(name, "true" if default else "false").strip().lower()
            if value in {"1", "true", "yes", "on"}:
                return True
            if value in {"0", "false", "no", "off"}:
                return False
            return default

        raw_hosts = env("ALLOWED_DOWNLOAD_HOSTS")
        allowed_hosts = tuple(host.strip() for host in raw_hosts.split(",") if host.strip())
        api_key = env("API_KEY") or os.getenv(
            "AIVS_VOLCENGINE_API_KEY", os.getenv("ARK_API_KEY", "")
        )
        return cls(
            base_url=env("BASE_URL", "https://ark.cn-beijing.volces.com/api/plan/v3"),
            api_key=api_key,
            model=env("MODEL", "doubao-seedance-2.0"),
            resolution=env("RESOLUTION", "720p"),
            ratio=env("RATIO", "9:16"),
            generate_audio=env_bool("GENERATE_AUDIO", False),
            watermark=env_bool("WATERMARK", False),
            reference_role=env("REFERENCE_ROLE"),
            poll_interval_seconds=env_float("POLL_INTERVAL_SECONDS", 10.0, 0, 60),
            max_wait_seconds=env_float("MAX_WAIT_SECONDS", 900.0, 5, 3_600),
            allowed_download_hosts=allowed_hosts,
        )

    @staticmethod
    def _error_for_status(status_code: int, phase: str) -> VideoProviderError:
        if status_code in {401, 403}:
            return VideoProviderError(
                "provider_auth_error",
                f"Volcengine Agent Plan {phase} authorization failed",
                retryable=False,
            )
        if status_code == 402:
            return VideoProviderError(
                "provider_insufficient_balance",
                "Volcengine Agent Plan "
                f"{phase} rejected because the account has insufficient balance",
                retryable=False,
            )
        if status_code in {400, 422}:
            return VideoProviderError(
                "provider_content_rejected",
                f"Volcengine Agent Plan {phase} rejected the request",
                retryable=False,
            )
        if status_code == 429:
            return VideoProviderError(
                "provider_rate_limited",
                f"Volcengine Agent Plan {phase} was rate limited",
                retryable=True,
            )
        if status_code >= 500:
            return VideoProviderError(
                "provider_unavailable",
                f"Volcengine Agent Plan {phase} is temporarily unavailable",
                retryable=True,
            )
        return VideoProviderError(
            "provider_request_rejected",
            f"Volcengine Agent Plan {phase} request was rejected",
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
                "provider_timeout", f"Volcengine Agent Plan {phase} request timed out"
            ) from exc
        except httpx.HTTPError as exc:
            raise VideoProviderError(
                "provider_unavailable", f"Volcengine Agent Plan {phase} request failed"
            ) from exc

        if response.is_error:
            raise self._error_for_status(response.status_code, phase)
        try:
            data = response.json()
        except ValueError as exc:
            raise VideoProviderError(
                "invalid_provider_response",
                f"Volcengine Agent Plan {phase} response was not JSON",
                retryable=False,
            ) from exc
        if not isinstance(data, dict):
            raise VideoProviderError(
                "invalid_provider_response",
                f"Volcengine Agent Plan {phase} response was not an object",
                retryable=False,
            )
        error = data.get("error")
        if isinstance(error, dict) and not data.get("status"):
            code = str(error.get("code", "provider_error")).lower()
            if "rate" in code or "quota" in code:
                raise VideoProviderError(
                    "provider_rate_limited", "Volcengine Agent Plan request was rate limited"
                )
            raise VideoProviderError(
                "provider_request_rejected",
                f"Volcengine Agent Plan returned {code}",
                retryable=False,
            )
        return data

    @staticmethod
    def _validate_reference_url(candidate: str) -> str:
        parsed = urlparse(candidate)
        if parsed.scheme in {"http", "https"} and parsed.hostname:
            return candidate
        if parsed.scheme == "asset" and parsed.netloc:
            return candidate
        if candidate.startswith("data:image/") and ";base64," in candidate:
            return candidate
        raise VideoProviderError(
            "invalid_reference_url",
            "Volcengine Agent Plan reference inputs must use public HTTP(S), asset "
            "or image data URLs",
            retryable=False,
        )

    @staticmethod
    def _task(data: dict[str, object]) -> dict[str, object]:
        task = data.get("task")
        if isinstance(task, dict):
            return task
        return data

    @staticmethod
    def _task_id(data: dict[str, object]) -> str | None:
        for key in ("id", "task_id"):
            value = data.get(key)
            if isinstance(value, (str, int)) and str(value):
                return str(value)
        return None

    @staticmethod
    def _video_url(data: dict[str, object]) -> object:
        content = data.get("content")
        if isinstance(content, dict):
            candidate = content.get("video_url")
            if isinstance(candidate, dict):
                return candidate.get("url")
            if candidate is not None:
                return candidate
        return data.get("video_url")

    def _validate_configuration(self) -> None:
        if not self.base_url or not self.api_key or not self.model:
            raise VideoProviderError(
                "provider_not_configured",
                "Volcengine Agent Plan video provider is not fully configured",
                retryable=False,
            )
        if self.resolution and self.resolution not in self.allowed_resolutions:
            raise VideoProviderError(
                "invalid_resolution",
                "Volcengine Agent Plan resolution must be 480p, 720p, 1080p or 4k",
                retryable=False,
            )
        if self.ratio not in self.allowed_ratios:
            raise VideoProviderError(
                "invalid_ratio",
                "Volcengine Agent Plan ratio must be adaptive, 21:9, 16:9, 4:3, 1:1, 3:4 or 9:16",
                retryable=False,
            )
        if self.reference_role not in self.allowed_reference_roles:
            raise VideoProviderError(
                "invalid_reference_role",
                "Volcengine Agent Plan reference role must be first_frame, last_frame "
                "or reference_image",
                retryable=False,
            )

    async def generate(
        self,
        *,
        prompt: str,
        duration_seconds: int,
        output_path: Path,
        reference_images: tuple[Path, ...] = (),
        reference_image_urls: tuple[str, ...] = (),
    ) -> Path:
        self._validate_configuration()
        if not prompt.strip():
            raise VideoProviderError(
                "invalid_prompt", "Volcengine Agent Plan prompt cannot be empty", retryable=False
            )
        if duration_seconds < 4 or duration_seconds > 15:
            raise VideoProviderError(
                "invalid_duration",
                "Volcengine Agent Plan duration must be an integer between 4 and 15 seconds",
                retryable=False,
            )
        if reference_images and not reference_image_urls:
            raise VideoProviderError(
                "reference_url_required",
                "Volcengine Agent Plan reference assets require public or provider asset URLs",
                retryable=False,
            )
        if len(reference_image_urls) > 9:
            raise VideoProviderError(
                "too_many_reference_images",
                "Volcengine Agent Plan accepts at most 9 reference images",
                retryable=False,
            )

        content: list[dict[str, object]] = [{"type": "text", "text": prompt.strip()}]
        for candidate in reference_image_urls:
            image_item: dict[str, object] = {
                "type": "image_url",
                "image_url": {"url": self._validate_reference_url(candidate)},
            }
            if self.reference_role:
                image_item["role"] = self.reference_role
            content.append(image_item)

        payload: dict[str, object] = {
            "model": self.model,
            "content": content,
            "generate_audio": self.generate_audio,
            "ratio": self.ratio,
            "duration": duration_seconds,
            "watermark": self.watermark,
        }
        if self.resolution:
            payload["resolution"] = self.resolution

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
                self._url("/contents/generations/tasks"),
                phase="submit",
                headers=headers,
                json=payload,
            )
            task_id = self._task_id(submitted)
            if task_id is None:
                raise VideoProviderError(
                    "invalid_provider_response",
                    "Volcengine Agent Plan submit response did not contain a task ID",
                    retryable=False,
                )

            download_url: str | None = None
            while time.monotonic() < deadline:
                status_data = await self._request_json(
                    client,
                    "GET",
                    self._url(f"/contents/generations/tasks/{task_id}"),
                    phase="poll",
                    headers=headers,
                )
                task = self._task(status_data)
                state = str(task.get("status", "")).lower()
                if state == "succeeded":
                    candidate = self._video_url(task)
                    if isinstance(candidate, str) and candidate:
                        download_url = candidate
                    if download_url is None:
                        raise VideoProviderError(
                            "invalid_provider_response",
                            "Volcengine Agent Plan succeeded without a video URL",
                            retryable=False,
                        )
                    break
                if state in {"failed", "cancelled", "canceled", "expired"}:
                    raise VideoProviderError(
                        "provider_job_failed",
                        f"Volcengine Agent Plan task ended with status {state}",
                        retryable=False,
                    )
                await asyncio.sleep(
                    min(self.poll_interval_seconds, max(0, deadline - time.monotonic()))
                )

            if download_url is None:
                raise VideoProviderError(
                    "provider_timeout", "Volcengine Agent Plan video task timed out"
                )
            safe_url = self._safe_download_url(download_url)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = output_path.with_suffix(f"{output_path.suffix}.download")
            try:
                # The returned URL is signed/TOS-owned; do not send the API key.
                async with client.stream("GET", safe_url) as response:
                    response.raise_for_status()
                    with temporary_path.open("wb") as handle:
                        async for chunk in response.aiter_bytes():
                            handle.write(chunk)
                temporary_path.replace(output_path)
            except httpx.TimeoutException as exc:
                temporary_path.unlink(missing_ok=True)
                raise VideoProviderError(
                    "provider_timeout", "Volcengine Agent Plan video download timed out"
                ) from exc
            except (httpx.HTTPError, OSError) as exc:
                temporary_path.unlink(missing_ok=True)
                raise VideoProviderError(
                    "provider_download_failed", "Volcengine Agent Plan video download failed"
                ) from exc
        return output_path


__all__ = ["VolcengineAgentPlanVideoProvider"]
