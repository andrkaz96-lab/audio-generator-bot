from __future__ import annotations

import tempfile
from abc import ABC, abstractmethod
from pathlib import Path


class TTSProviderError(RuntimeError):
    """Base provider error with optional user-facing message."""


class TTSProviderTimeoutError(TTSProviderError):
    def __init__(self, provider_name: str, timeout_seconds: int) -> None:
        super().__init__(
            f"Провайдер {provider_name} превысил таймаут синтеза ({timeout_seconds} сек)."
        )
        self.user_message = str(self)
        self.provider_name = provider_name
        self.timeout_seconds = timeout_seconds


class TTSProviderUnavailableError(TTSProviderError):
    def __init__(self, provider_name: str, message: str) -> None:
        super().__init__(message)
        self.user_message = message
        self.provider_name = provider_name


class TTSProvider(ABC):
    async def preload(self) -> None:
        """Prepare provider resources before the first synthesize call."""

    async def reset(self) -> None:
        """Reset provider runtime state after fatal errors/timeouts."""

    @property
    def provider_name(self) -> str:
        return self.__class__.__name__

    @property
    def is_local(self) -> bool:
        return False

    @abstractmethod
    async def synthesize_to_file(
        self,
        text: str,
        destination: Path,
        *,
        timeout_seconds: int | None = None,
    ) -> None:
        """Write audio to destination without materializing full output in memory."""

    async def synthesize(self, text: str) -> bytes:
        with tempfile.TemporaryDirectory() as tmpdir:
            destination = Path(tmpdir) / "speech.mp3"
            await self.synthesize_to_file(text, destination)
            return destination.read_bytes()
