from __future__ import annotations

import asyncio
from pathlib import Path

from gtts import gTTS

from .base import TTSProvider


class GTTSProvider(TTSProvider):
    def __init__(self, lang: str = "ru") -> None:
        self._lang = lang

    async def synthesize_to_file(
        self,
        text: str,
        destination: Path,
        *,
        timeout_seconds: int | None = None,
    ) -> None:
        _ = timeout_seconds
        await asyncio.to_thread(self._synthesize_sync_to_file, text, destination)

    def _synthesize_sync_to_file(self, text: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        tts = gTTS(text=text, lang=self._lang)
        with destination.open("wb") as output:
            tts.write_to_fp(output)
