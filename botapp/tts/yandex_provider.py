from __future__ import annotations

from .base import TTSProvider


class YandexSpeechKitProvider(TTSProvider):
    def __init__(self) -> None:
        raise NotImplementedError(
            "YandexSpeechKitProvider is not configured yet. "
            "Use TTS_PROVIDER=edge for local run, then add cloud creds and implementation."
        )

    async def synthesize(self, text: str) -> bytes:
        raise NotImplementedError
