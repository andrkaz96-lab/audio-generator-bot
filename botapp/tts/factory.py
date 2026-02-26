from __future__ import annotations

from botapp.config import Settings

from .base import TTSProvider
from .edge_provider import EdgeTTSProvider
from .fallback_provider import FallbackTTSProvider
from .gtts_provider import GTTSProvider
from .silero_provider import SileroTTSProvider
from .yandex_provider import YandexSpeechKitProvider



def make_tts_provider(settings: Settings) -> TTSProvider:
    if settings.tts_provider == "silero":
        primary = SileroTTSProvider(
            speaker=settings.silero_speaker,
            sample_rate=settings.silero_sample_rate,
            model_language=settings.silero_model_language,
            model_speaker=settings.silero_model_speaker,
        )
        fallback = GTTSProvider(lang=settings.gtts_lang)
        return FallbackTTSProvider(primary=primary, fallback=fallback)
    if settings.tts_provider == "gtts":
        return GTTSProvider(lang=settings.gtts_lang)
    if settings.tts_provider == "edge":
        return EdgeTTSProvider(voice=settings.edge_voice)
    if settings.tts_provider == "yandex":
        return YandexSpeechKitProvider()

    raise ValueError(f"Unsupported TTS provider: {settings.tts_provider}")
