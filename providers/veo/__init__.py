"""Google Veo transport-compatible provider scaffold."""

from __future__ import annotations

from packages.providers.http_video import HTTPVideoProvider


class GoogleVeoVideoProvider(HTTPVideoProvider):
    provider_id = "google-veo"

    @classmethod
    def from_env(cls) -> GoogleVeoVideoProvider:
        return super().from_env(provider_id=cls.provider_id, env_prefix="AIVS_VEO_VIDEO")


__all__ = ["GoogleVeoVideoProvider"]
