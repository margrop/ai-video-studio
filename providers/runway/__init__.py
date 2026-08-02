"""Runway transport-compatible provider scaffold."""

from __future__ import annotations

from packages.providers.http_video import HTTPVideoProvider


class RunwayVideoProvider(HTTPVideoProvider):
    provider_id = "runway"

    @classmethod
    def from_env(cls) -> RunwayVideoProvider:
        return super().from_env(provider_id=cls.provider_id, env_prefix="AIVS_RUNWAY_VIDEO")


__all__ = ["RunwayVideoProvider"]
