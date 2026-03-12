from __future__ import annotations

from abc import ABC, abstractmethod


class TTSProvider(ABC):
    async def preload(self) -> None:
        """Prepare provider resources before the first synthesize call."""

    @property
    def provider_name(self) -> str:
        return self.__class__.__name__

    @abstractmethod
    async def synthesize(self, text: str) -> bytes:
        """Return audio as bytes (mp3)."""
