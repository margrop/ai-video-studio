"""TTS contract kept independent from video rendering."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class TTSProvider(Protocol):
    provider_id: str

    async def synthesize(
        self,
        *,
        text: str,
        voice: str,
        language: str,
        output_path: Path,
        timeout_seconds: float,
    ) -> Path:
        """Write an audio artifact and return its path."""
