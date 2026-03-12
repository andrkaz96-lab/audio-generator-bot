from __future__ import annotations

import logging

from .base import TTSProvider


logger = logging.getLogger(__name__)


class FallbackTTSProvider(TTSProvider):
    def __init__(self, primary: TTSProvider, fallback: TTSProvider) -> None:
        self._primary = primary
        self._fallback = fallback
        self._use_fallback = False

    @property
    def provider_name(self) -> str:
        return f"{self._primary.provider_name}->{self._fallback.provider_name}"

    async def preload(self) -> None:
        logger.info(
            "TTS provider selection",
            extra={
                "provider_name": self._primary.provider_name,
                "fallback_provider_name": self._fallback.provider_name,
            },
        )
        try:
            await self._primary.preload()
            logger.info(
                "Primary TTS preload result",
                extra={
                    "provider_name": self._primary.provider_name,
                    "fallback_provider_name": self._fallback.provider_name,
                    "preload_success": True,
                    "model_source": "local_cache",
                },
            )
        except Exception as exc:
            logger.warning(
                "Primary TTS preload failed, fallback will be used",
                extra={
                    "provider_name": self._primary.provider_name,
                    "fallback_provider_name": self._fallback.provider_name,
                    "preload_success": False,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
            self._use_fallback = True

        try:
            await self._fallback.preload()
        except Exception as exc:
            logger.warning(
                "Fallback TTS preload failed",
                extra={
                    "provider_name": self._fallback.provider_name,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "preload_success": False,
                },
            )

    async def synthesize(self, text: str) -> bytes:
        if self._use_fallback:
            return await self._fallback.synthesize(text)

        try:
            return await self._primary.synthesize(text)
        except Exception as exc:
            logger.warning(
                "Primary TTS provider failed, switching to fallback",
                extra={
                    "provider_name": self._primary.provider_name,
                    "fallback_provider_name": self._fallback.provider_name,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
            self._use_fallback = True
            try:
                return await self._fallback.synthesize(text)
            except Exception as fallback_exc:
                logger.error(
                    "Fallback TTS provider failed",
                    extra={
                        "provider_name": self._fallback.provider_name,
                        "error_type": type(fallback_exc).__name__,
                        "error_message": str(fallback_exc),
                    },
                )
                raise RuntimeError(
                    "Не удалось синтезировать аудио: primary и fallback TTS недоступны. "
                    "Проверьте настройки TTS_PROVIDER и предзагрузку модели."
                ) from fallback_exc
