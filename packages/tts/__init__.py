"""Text-to-speech provider interfaces and offline audio fallback."""

from .base import TTSProvider
from .silent import SilentTTSProvider

__all__ = ["SilentTTSProvider", "TTSProvider"]
