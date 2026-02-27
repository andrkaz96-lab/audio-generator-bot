from dataclasses import dataclass
import os

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    tts_provider: str = "silero"
    edge_voice: str = "ru-RU-DmitryNeural"
    gtts_lang: str = "ru"
    silero_speaker: str = "xenia"
    silero_sample_rate: int = 48000
    silero_model_language: str = "ru"
    silero_model_speaker: str = "v4_ru"
    max_chars_per_chunk: int = 4000
    max_input_chars: int = 60000
    request_timeout_seconds: int = 20
    telegram_api_timeout_seconds: int = 120
    telegram_api_retries: int = 3
    posthog_api_key: str = ""
    posthog_project_id: str = ""
    posthog_host: str = "https://app.posthog.com"
    analytics_enabled: bool = True



def load_settings() -> Settings:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")

    return Settings(
        telegram_bot_token=token,
        tts_provider=os.getenv("TTS_PROVIDER", "silero").strip().lower(),
        edge_voice=os.getenv("EDGE_VOICE", "ru-RU-DmitryNeural").strip(),
        gtts_lang=os.getenv("GTTS_LANG", "ru").strip(),
        silero_speaker=os.getenv("SILERO_SPEAKER", "xenia").strip(),
        silero_sample_rate=int(os.getenv("SILERO_SAMPLE_RATE", "48000")),
        silero_model_language=os.getenv("SILERO_MODEL_LANGUAGE", "ru").strip(),
        silero_model_speaker=os.getenv("SILERO_MODEL_SPEAKER", "v4_ru").strip(),
        max_chars_per_chunk=int(os.getenv("MAX_CHARS_PER_CHUNK", "4000")),
        max_input_chars=int(os.getenv("MAX_INPUT_CHARS", "60000")),
        request_timeout_seconds=int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20")),
        telegram_api_timeout_seconds=int(os.getenv("TELEGRAM_API_TIMEOUT_SECONDS", "120")),
        telegram_api_retries=int(os.getenv("TELEGRAM_API_RETRIES", "3")),
        posthog_api_key=os.getenv("POSTHOG_API_KEY", "").strip(),
        posthog_project_id=os.getenv("POSTHOG_PROJECT_ID", "").strip(),
        posthog_host=os.getenv("POSTHOG_HOST", "https://app.posthog.com").strip(),
        analytics_enabled=os.getenv("ANALYTICS_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"},
    )
