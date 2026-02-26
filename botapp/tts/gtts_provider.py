from __future__ import annotations

import asyncio
from io import BytesIO

from gtts import gTTS

from .base import TTSProvider


class GTTSProvider(TTSProvider):
    def __init__(self, lang: str = "ru") -> None:
        self._lang = lang

    async def synthesize(self, text: str) -> bytes:
        return await asyncio.to_thread(self._synthesize_sync, text)

    def _synthesize_sync(self, text: str) -> bytes:
        buffer = BytesIO()
        tts = gTTS(text=text, lang=self._lang)
        tts.write_to_fp(buffer)
        return buffer.getvalue()
