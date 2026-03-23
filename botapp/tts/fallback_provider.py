from __future__ import annotations

import logging
from pathlib import Path

from .base import TTSProvider, TTSProviderTimeoutError, TTSProviderUnavailableError


logger = logging.getLogger(__name__)


class FallbackTTSProvider(TTSProvider):
    def __init__(self, primary: TTSProvider, fallback: TTSProvider) -> None:
        self._primary = primary
        self._fallback = fallback
        self._use_fallback = False

    @property
    def provider_name(self) -> str:
        return f"{self._primary.provider_name}->{self._fallback.provider_name}"

    @property
    def is_local(self) -> bool:
        return self._primary.is_local

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

    async def reset(self) -> None:
        await self._primary.reset()
        await self._fallback.reset()

    async def synthesize_to_file(
        self,
        text: str,
        destination: Path,
        *,
        timeout_seconds: int | None = None,
    ) -> None:
        if self._use_fallback:
            await self._fallback.synthesize_to_file(
                text,
                destination,
                timeout_seconds=timeout_seconds,
            )
            return

        try:
            await self._primary.synthesize_to_file(
                text,
                destination,
                timeout_seconds=timeout_seconds,
            )
            return
        except Exception as exc:
            logger.warning(
                "Primary TTS provider failed, switching to fallback",
                extra={
                    "provider_name": self._primary.provider_name,
                    "fallback_provider_name": self._fallback.provider_name,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "timeout_seconds": timeout_seconds,
                },
            )
            await self._primary.reset()
            self._use_fallback = True

            try:
                await self._fallback.synthesize_to_file(
                    text,
                    destination,
                    timeout_seconds=timeout_seconds,
                )
                return
            except Exception as fallback_exc:
                logger.error(
                    "Fallback TTS provider failed",
                    extra={
                        "provider_name": self._fallback.provider_name,
                        "error_type": type(fallback_exc).__name__,
                        "error_message": str(fallback_exc),
                    },
                )
                if isinstance(exc, TTSProviderTimeoutError):
                    raise exc
                raise TTSProviderUnavailableError(
                    self.provider_name,
                    "Не удалось синтезировать аудио: primary и fallback TTS недоступны. "
                    "Проверьте настройки TTS_PROVIDER и предзагрузку модели.",
                ) from fallback_exc
