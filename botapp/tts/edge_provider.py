from __future__ import annotations

import edge_tts

from .base import TTSProvider


class EdgeTTSProvider(TTSProvider):
    def __init__(self, voice: str) -> None:
        self._voice = voice

    async def synthesize(self, text: str) -> bytes:
        communicate = edge_tts.Communicate(text=text, voice=self._voice)
        result = bytearray()

        async for chunk in communicate.stream():
            if chunk.get("type") == "audio":
                result.extend(chunk.get("data", b""))

        return bytes(result)
