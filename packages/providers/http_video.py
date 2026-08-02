"""Generic asynchronous HTTP video adapter.

This is a provider-neutral transport contract, not a claim that every vendor
uses the same API. A vendor directory can subclass it when request or polling
semantics differ, while the workflow continues to depend on ``VideoProvider``.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .base import VideoProviderError


class HTTPVideoProvider:
    """Submit, poll and download a server-configured asynchronous video job."""

    provider_kind = "video"
    capabilities = ("async-generation", "remote-download", "shot-generation")

    def __init__(
        self,
        *,
        provider_id: str,
        base_url: str,
        api_key: str,
        model: str,
        submit_path: str = "/videos/generations",
        poll_path_template: str = "/videos/{job_id}",
        poll_interval_seconds: float = 2.0,
        max_wait_seconds: float = 300.0,
        allowed_download_hosts: tuple[str, ...] = (),
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.provider_id = provider_id
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.submit_path = submit_path
        self.poll_path_template = poll_path_template
        self.poll_interval_seconds = max(0.0, poll_interval_seconds)
        self.max_wait_seconds = max(5.0, max_wait_seconds)
        base_host = urlparse(self.base_url).hostname
        self.allowed_download_hosts = tuple(
            sorted(set(host for host in (base_host, *allowed_download_hosts) if host))
        )
        self.transport = transport

    @classmethod
    def from_env(cls, *, provider_id: str) -> HTTPVideoProvider:
        def env_float(name: str, default: float, minimum: float, maximum: float) -> float:
            try:
                value = float(os.getenv(name, str(default)))
            except ValueError:
                return default
            return value if minimum <= value <= maximum else default

        raw_hosts = os.getenv("AIVS_VIDEO_ALLOWED_DOWNLOAD_HOSTS", "")
        allowed_hosts = tuple(host.strip() for host in raw_hosts.split(",") if host.strip())
        return cls(
            provider_id=provider_id,
            base_url=os.getenv("AIVS_VIDEO_BASE_URL", ""),
            api_key=os.getenv("AIVS_VIDEO_API_KEY", ""),
            model=os.getenv("AIVS_VIDEO_MODEL", ""),
            submit_path=os.getenv("AIVS_VIDEO_SUBMIT_PATH", "/videos/generations"),
            poll_path_template=os.getenv("AIVS_VIDEO_POLL_PATH", "/videos/{job_id}"),
            poll_interval_seconds=env_float("AIVS_VIDEO_POLL_INTERVAL_SECONDS", 2.0, 0, 60),
            max_wait_seconds=env_float("AIVS_VIDEO_MAX_WAIT_SECONDS", 300.0, 5, 3_600),
            allowed_download_hosts=allowed_hosts,
        )

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{self.base_url}{path}"

    def _safe_download_url(self, candidate: object) -> str:
        if not isinstance(candidate, str) or not candidate:
            raise VideoProviderError(
                "invalid_provider_response",
                "video provider did not return a download URL",
                retryable=False,
            )
        parsed = urlparse(candidate)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in self.allowed_download_hosts
        ):
            raise VideoProviderError(
                "unsafe_download_url",
                "video provider returned a URL outside the configured allow-list",
                retryable=False,
            )
        return candidate

    @staticmethod
    def _video_url(data: dict[str, object]) -> object:
        for key in ("video_url", "output_url", "url"):
            if key in data:
                return data[key]
        output = data.get("output")
        if isinstance(output, dict):
            for key in ("video_url", "url"):
                if key in output:
                    return output[key]
        return None

    @staticmethod
    def _job_id(data: dict[str, object]) -> str | None:
        for key in ("id", "job_id", "task_id"):
            value = data.get(key)
            if isinstance(value, (str, int)) and str(value):
                return str(value)
        return None

    async def _json_request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        **kwargs: object,
    ) -> dict[str, object]:
        try:
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            data = response.json()
        except httpx.TimeoutException as exc:
            raise VideoProviderError(
                "provider_timeout", "video provider request timed out"
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise VideoProviderError(
                "provider_unavailable", "video provider request failed"
            ) from exc
        if not isinstance(data, dict):
            raise VideoProviderError(
                "invalid_provider_response",
                "video provider response was not an object",
                retryable=False,
            )
        return data

    async def generate(
        self,
        *,
        prompt: str,
        duration_seconds: int,
        output_path: Path,
        reference_images: tuple[Path, ...] = (),
    ) -> Path:
        if not self.base_url or not self.api_key or not self.model:
            raise VideoProviderError(
                "provider_not_configured",
                "video provider is not fully configured",
                retryable=False,
            )
        _ = reference_images
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": self.model,
            "prompt": prompt,
            "duration_seconds": duration_seconds,
        }
        deadline = time.monotonic() + self.max_wait_seconds
        async with httpx.AsyncClient(timeout=45.0, transport=self.transport) as client:
            submitted = await self._json_request(
                client,
                "POST",
                self._url(self.submit_path),
                headers=headers,
                json=payload,
            )
            download_url = self._video_url(submitted)
            if download_url is None:
                job_id = self._job_id(submitted)
                if job_id is None:
                    raise VideoProviderError(
                        "invalid_provider_response",
                        "video provider did not return a job ID",
                        retryable=False,
                    )
                while time.monotonic() < deadline:
                    status_data = await self._json_request(
                        client,
                        "GET",
                        self._url(self.poll_path_template.format(job_id=job_id)),
                        headers=headers,
                    )
                    state = str(status_data.get("status", "")).lower()
                    if state in {"succeeded", "completed", "success", "done"}:
                        download_url = self._video_url(status_data)
                        break
                    if state in {"failed", "error", "cancelled", "canceled"}:
                        raise VideoProviderError(
                            "provider_job_failed",
                            "video provider reported a failed job",
                            retryable=False,
                        )
                    await asyncio.sleep(
                        min(self.poll_interval_seconds, max(0, deadline - time.monotonic()))
                    )
                if download_url is None:
                    raise VideoProviderError("provider_timeout", "video provider job timed out")

            safe_url = self._safe_download_url(download_url)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = output_path.with_suffix(f"{output_path.suffix}.download")
            try:
                # Signed/CDN download URLs must not receive the Provider API key.
                async with client.stream("GET", safe_url) as response:
                    response.raise_for_status()
                    with temporary_path.open("wb") as handle:
                        async for chunk in response.aiter_bytes():
                            handle.write(chunk)
                temporary_path.replace(output_path)
            except httpx.TimeoutException as exc:
                temporary_path.unlink(missing_ok=True)
                raise VideoProviderError("provider_timeout", "video download timed out") from exc
            except (httpx.HTTPError, OSError) as exc:
                temporary_path.unlink(missing_ok=True)
                raise VideoProviderError(
                    "provider_download_failed", "video download failed"
                ) from exc
        return output_path
