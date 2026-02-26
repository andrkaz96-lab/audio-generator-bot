from __future__ import annotations

import logging

from .base import TTSProvider


logger = logging.getLogger(__name__)


class FallbackTTSProvider(TTSProvider):
    def __init__(self, primary: TTSProvider, fallback: TTSProvider) -> None:
        self._primary = primary
        self._fallback = fallback
        self._use_fallback = False

    async def synthesize(self, text: str) -> bytes:
        if self._use_fallback:
            return await self._fallback.synthesize(text)

        try:
            return await self._primary.synthesize(text)
        except Exception as exc:
            logger.warning(
                "Primary TTS provider failed, switching to fallback. Error: %s: %s",
                type(exc).__name__,
                exc,
            )
            self._use_fallback = True
            return await self._fallback.synthesize(text)
