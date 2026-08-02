"""Prompt composition is kept deterministic and independent of any LLM."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class PromptBuilder:
    base_prompt: str = "clean vertical short-video composition, coherent visual language"
    character_prompt: str = ""
    lighting_prompt: str = "soft natural light, high legibility, controlled contrast"
    negative_prompt: str = "blurry, distorted text, extra limbs, watermark, logo artifacts"

    @classmethod
    def from_config(cls, config: Mapping[str, str]) -> PromptBuilder:
        return cls(
            base_prompt=config.get("base", cls.base_prompt),
            lighting_prompt=config.get("lighting", cls.lighting_prompt),
            negative_prompt=config.get("negative", cls.negative_prompt),
        )

    def build(self, *, visual: str, camera: str = "medium shot", character: str = "") -> str:
        parts = [
            self.base_prompt,
            visual.strip(),
            character.strip() or self.character_prompt,
            f"camera: {camera.strip()}",
            self.lighting_prompt,
            f"negative: {self.negative_prompt}",
        ]
        return ", ".join(part for part in parts if part)
