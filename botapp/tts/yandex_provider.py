from __future__ import annotations

from pathlib import Path

from .base import TTSProvider


class YandexSpeechKitProvider(TTSProvider):
    def __init__(self) -> None:
        raise NotImplementedError(
            "YandexSpeechKitProvider is not configured yet. "
            "Use TTS_PROVIDER=edge for local run, then add cloud creds and implementation."
        )

    async def synthesize_to_file(
        self,
        text: str,
        destination: Path,
        *,
        timeout_seconds: int | None = None,
    ) -> None:
        _ = text, destination, timeout_seconds
        raise NotImplementedError
