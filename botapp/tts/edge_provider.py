from __future__ import annotations

from pathlib import Path

import edge_tts

from .base import TTSProvider


class EdgeTTSProvider(TTSProvider):
    def __init__(self, voice: str) -> None:
        self._voice = voice

    async def synthesize_to_file(
        self,
        text: str,
        destination: Path,
        *,
        timeout_seconds: int | None = None,
    ) -> None:
        _ = timeout_seconds
        destination.parent.mkdir(parents=True, exist_ok=True)
        communicate = edge_tts.Communicate(text=text, voice=self._voice)
        with destination.open("wb") as output:
            async for chunk in communicate.stream():
                if chunk.get("type") == "audio":
                    output.write(chunk.get("data", b""))
