from __future__ import annotations

from abc import ABC, abstractmethod


class TTSProvider(ABC):
    @abstractmethod
    async def synthesize(self, text: str) -> bytes:
        """Return audio as bytes (mp3)."""
