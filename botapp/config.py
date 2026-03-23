from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


def _as_bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


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
    silero_repo_dir: str = str(
        Path.home() / ".cache" / "audio-generator-bot" / "silero-models"
    )
    silero_allow_download_on_startup: bool = True
    max_chars_per_chunk: int = 220
    max_sentences_per_chunk: int = 3
    max_words_per_chunk: int = 60
    min_chars_per_chunk: int = 80
    max_input_chars: int = 0
    request_timeout_seconds: int = 20
    telegram_api_timeout_seconds: int = 120
    telegram_api_retries: int = 3
    tts_chunk_timeout_seconds: int = 45
    tts_overall_timeout_seconds: int = 900
    tts_chunk_retry_count: int = 1
    tts_temp_dir: str = ""
    tts_cleanup_temp_files: bool = True
    posthog_api_key: str = ""
    posthog_project_id: str = ""
    posthog_host: str = "https://app.posthog.com"
    analytics_enabled: bool = True
    llm_enabled: bool = True
    llm_provider: str = "yandex"
    yandex_api_key: str = ""
    yandex_folder_id: str = "b1geq9r8nerbilj0i53p"
    yandex_api_base: str = "https://llm.api.cloud.yandex.net/v1"
    yandex_model: str = "yandexgpt-lite/latest"
    llm_timeout_seconds: int = 30
    llm_max_input_chars: int = 18000
    llm_debug_send_text_file: bool = True
    llm_log_prompts: bool = False


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
        silero_repo_dir=os.getenv(
            "SILERO_REPO_DIR",
            str(Path.home() / ".cache" / "audio-generator-bot" / "silero-models"),
        ).strip(),
        silero_allow_download_on_startup=_as_bool(
            "SILERO_ALLOW_DOWNLOAD_ON_STARTUP", "true"
        ),
        max_chars_per_chunk=int(os.getenv("MAX_CHARS_PER_CHUNK", "220")),
        max_sentences_per_chunk=int(os.getenv("MAX_SENTENCES_PER_CHUNK", "3")),
        max_words_per_chunk=int(os.getenv("MAX_WORDS_PER_CHUNK", "60")),
        min_chars_per_chunk=int(os.getenv("MIN_CHARS_PER_CHUNK", "80")),
        max_input_chars=int(os.getenv("MAX_INPUT_CHARS", "0")),
        request_timeout_seconds=int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20")),
        telegram_api_timeout_seconds=int(
            os.getenv("TELEGRAM_API_TIMEOUT_SECONDS", "120")
        ),
        telegram_api_retries=int(os.getenv("TELEGRAM_API_RETRIES", "3")),
        tts_chunk_timeout_seconds=int(os.getenv("TTS_CHUNK_TIMEOUT_SECONDS", "45")),
        tts_overall_timeout_seconds=int(
            os.getenv("TTS_OVERALL_TIMEOUT_SECONDS", "900")
        ),
        tts_chunk_retry_count=int(os.getenv("TTS_CHUNK_RETRY_COUNT", "1")),
        tts_temp_dir=os.getenv("TTS_TEMP_DIR", "").strip(),
        tts_cleanup_temp_files=_as_bool("TTS_CLEANUP_TEMP_FILES", "true"),
        posthog_api_key=os.getenv("POSTHOG_API_KEY", "").strip(),
        posthog_project_id=os.getenv("POSTHOG_PROJECT_ID", "").strip(),
        posthog_host=os.getenv("POSTHOG_HOST", "https://app.posthog.com").strip(),
        analytics_enabled=_as_bool("ANALYTICS_ENABLED", "true"),
        llm_enabled=_as_bool("LLM_ENABLED", "true"),
        llm_provider=os.getenv("LLM_PROVIDER", "yandex").strip().lower(),
        yandex_api_key=os.getenv("YANDEX_API_KEY", "").strip(),
        yandex_folder_id=os.getenv("YANDEX_FOLDER_ID", "b1geq9r8nerbilj0i53p").strip(),
        yandex_api_base=os.getenv(
            "YANDEX_API_BASE", "https://llm.api.cloud.yandex.net/v1"
        ).strip(),
        yandex_model=os.getenv("YANDEX_MODEL", "yandexgpt-lite/latest").strip(),
        llm_timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS", "30")),
        llm_max_input_chars=int(os.getenv("LLM_MAX_INPUT_CHARS", "18000")),
        llm_debug_send_text_file=_as_bool("LLM_DEBUG_SEND_TEXT_FILE", "true"),
        llm_log_prompts=_as_bool("LLM_LOG_PROMPTS", "false"),
    )
