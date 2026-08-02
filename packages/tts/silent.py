"""A deterministic silent WAV for offline demos and failure-safe rendering."""

from __future__ import annotations

import asyncio
import wave
from pathlib import Path


class SilentTTSProvider:
    provider_id = "silent-offline"

    async def synthesize(
        self,
        *,
        text: str,
        voice: str,
        language: str,
        output_path: Path,
        timeout_seconds: float,
    ) -> Path:
        _ = (voice, language, timeout_seconds)
        # A readable 16 kHz mono WAV lets FFmpeg produce a valid MP4 without
        # requiring an operating-system TTS binary. Duration is estimated from
        # Chinese/Latin text and is capped by the output pipeline.
        duration = max(1.0, min(180.0, len(text) / 4.0))

        def write() -> None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            frame_count = int(duration * 16_000)
            with wave.open(str(output_path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16_000)
                audio.writeframes(b"\x00\x00" * frame_count)

        await asyncio.to_thread(write)
        return output_path
