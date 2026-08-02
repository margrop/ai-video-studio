"""Optional OpenAI-compatible speech adapter for a server-side TTS endpoint."""

from __future__ import annotations

from pathlib import Path

import httpx


class OpenAICompatibleTTSProvider:
    provider_id = "openai-compatible-tts"

    def __init__(self, *, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    async def synthesize(
        self,
        *,
        text: str,
        voice: str,
        language: str,
        output_path: Path,
        timeout_seconds: float,
    ) -> Path:
        if not self.base_url or not self.api_key or not self.model:
            raise RuntimeError("TTS provider is not fully configured")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        response_format = "wav"
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/audio/speech",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.model,
                        "input": text,
                        "voice": voice,
                        "response_format": response_format,
                        "language": language,
                    },
                )
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise RuntimeError("TTS request timed out") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError("TTS request failed") from exc
        output_path.write_bytes(response.content)
        return output_path
