"""Kling transport-compatible provider scaffold."""

from __future__ import annotations

from packages.providers.http_video import HTTPVideoProvider


class KlingVideoProvider(HTTPVideoProvider):
    provider_id = "kling"

    @classmethod
    def from_env(cls) -> KlingVideoProvider:
        return super().from_env(provider_id=cls.provider_id, env_prefix="AIVS_KLING_VIDEO")


__all__ = ["KlingVideoProvider"]
