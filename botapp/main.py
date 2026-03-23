from __future__ import annotations

import asyncio
import logging
import tempfile
import time
from pathlib import Path
from typing import Awaitable, Callable, TypeVar

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.filters import CommandStart
from aiogram.types import (
    FSInputFile,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from botapp.analytics import EventLogger
from botapp.config import load_settings
from botapp.runtime_metrics import TTSRuntimeTracker
from botapp.extractors.input_resolver import resolve_input_text
from botapp.extractors.article_pipeline import ArticleMode, run_article_pipeline
from botapp.extractors.url_text import extract_url
from botapp.llm.service import ArticleLLMService
from botapp.llm.yandex_client import YandexLLMClient
from botapp.tts.factory import make_tts_provider
from botapp.tts.pipeline import (
    TTSProgressEvent,
    TTSPipeline,
    TTSPipelineConfig,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


settings = load_settings()
tts_provider = make_tts_provider(settings)
event_logger = EventLogger(
    api_key=settings.posthog_api_key,
    host=settings.posthog_host,
    enabled=settings.analytics_enabled,
)
llm_client = (
    YandexLLMClient(
        api_key=settings.yandex_api_key,
        folder_id=settings.yandex_folder_id,
        api_base=settings.yandex_api_base,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    if settings.yandex_api_key
    else None
)
llm_service = ArticleLLMService(
    enabled=settings.llm_enabled,
    provider=settings.llm_provider,
    model=settings.yandex_model,
    max_input_chars=settings.llm_max_input_chars,
    log_prompts=settings.llm_log_prompts,
    client=llm_client,
)

dp = Dispatcher()
T = TypeVar("T")
runtime_tracker = TTSRuntimeTracker()
_tts_job_semaphore = asyncio.Semaphore(max(1, settings.tts_max_concurrent_jobs))
_tts_synth_semaphore = asyncio.Semaphore(max(1, settings.tts_max_concurrent_synths))
MODE_CLOSE_TO_SOURCE = "close_to_source"
MODE_AUDIO_ADAPTED = "audio_adapted"
MODE_AUDIO_SUMMARY = "audio_summary"
MODE_BUTTON_TO_VALUE: dict[str, ArticleMode] = {
    "🧾 Близко к оригиналу": MODE_CLOSE_TO_SOURCE,
    "🎧 Под слух": MODE_AUDIO_ADAPTED,
    "⚡ Коротко под слух": MODE_AUDIO_SUMMARY,
}
LEGACY_MODE_BUTTON_TO_VALUE: dict[str, ArticleMode] = {
    "🧾 Почти дословно": MODE_CLOSE_TO_SOURCE,
    "🎧 Чистый для озвучки": MODE_AUDIO_ADAPTED,
}
_pending_url_by_user: dict[int, str] = {}


class UserVisibleError(RuntimeError):
    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


class ProcessingTimeoutError(UserVisibleError):
    def __init__(self, *, step: str, timeout_seconds: int) -> None:
        super().__init__(
            "Ошибка: операция зависла и была остановлена. "
            f"Шаг: {step}. Таймаут: {timeout_seconds} сек. "
            "Попробуйте повторить запрос или уменьшить объем текста."
        )
        self.step = step
        self.timeout_seconds = timeout_seconds


async def with_telegram_retries(
    operation: Callable[[], Awaitable[T]], retries: int
) -> T:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return await operation()
        except TelegramNetworkError as exc:
            last_error = exc
            if attempt == retries:
                break
            await asyncio.sleep(min(attempt, 3))
    assert last_error is not None
    raise last_error


async def safe_update_status(
    status_message: Message | None,
    text: str,
    fallback_message_source: Message,
) -> Message | None:
    chat_id = fallback_message_source.chat.id if fallback_message_source.chat else None
    status_message_id = status_message.message_id if status_message else None
    current_text = (status_message.text or "") if status_message else ""

    if status_message is not None and current_text == text:
        logger.info(
            "status_update skipped: chat_id=%s status_message_id=%s edit_attempted=false edit_failed=false "
            "fallback_to_new_message=false exception_text=",
            chat_id,
            status_message_id,
        )
        return status_message

    if status_message is None:
        logger.warning(
            "status_update fallback: chat_id=%s status_message_id=%s edit_attempted=false edit_failed=true "
            "fallback_to_new_message=true exception_text=status_message is missing",
            chat_id,
            status_message_id,
        )
        return await with_telegram_retries(
            lambda: fallback_message_source.answer(text),
            retries=settings.telegram_api_retries,
        )

    try:
        updated_message = await with_telegram_retries(
            lambda: status_message.edit_text(text),
            retries=settings.telegram_api_retries,
        )
        logger.info(
            "status_update success: chat_id=%s status_message_id=%s edit_attempted=true edit_failed=false "
            "fallback_to_new_message=false exception_text=",
            chat_id,
            status_message_id,
        )
        return updated_message
    except TelegramBadRequest as exc:
        exc_text = str(exc)
        if "message can't be edited" not in exc_text.lower():
            raise

        logger.warning(
            "status_update edit failed: chat_id=%s status_message_id=%s edit_attempted=true edit_failed=true "
            "fallback_to_new_message=true exception_text=%s",
            chat_id,
            status_message_id,
            exc_text,
        )
        return await with_telegram_retries(
            lambda: fallback_message_source.answer(text),
            retries=settings.telegram_api_retries,
        )


async def _run_with_timeout(
    operation: Awaitable[T],
    *,
    timeout_seconds: int,
    step: str,
) -> T:
    try:
        return await asyncio.wait_for(operation, timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        logger.exception(
            "operation timeout: step=%s timeout_seconds=%s",
            step,
            timeout_seconds,
        )
        raise ProcessingTimeoutError(
            step=step,
            timeout_seconds=timeout_seconds,
        ) from exc


def _prepare_tts_input(text: str) -> tuple[str, bool]:
    max_input_chars = settings.max_input_chars
    if max_input_chars <= 0 or len(text) <= max_input_chars:
        return text, False

    truncated = text[:max_input_chars]
    logger.warning(
        "tts input truncated: original_chars=%s truncated_chars=%s",
        len(text),
        len(truncated),
    )
    return truncated, True


def _resolve_tts_chunk_size(text: str) -> int:
    chunk_size = settings.max_chars_per_chunk
    if chunk_size <= 0:
        raise ValueError("MAX_CHARS_PER_CHUNK must be > 0")
    return min(len(text), chunk_size) if text else chunk_size


def _make_tts_pipeline(
    progress_callback: Callable[[TTSProgressEvent], Awaitable[None]] | None = None,
) -> TTSPipeline:
    config = TTSPipelineConfig.from_limits(
        max_chars_per_chunk=settings.max_chars_per_chunk,
        max_sentences_per_chunk=settings.max_sentences_per_chunk,
        max_words_per_chunk=settings.max_words_per_chunk,
        min_chars_per_chunk=settings.min_chars_per_chunk,
        retry_count=settings.tts_chunk_retry_count,
        per_chunk_timeout_seconds=settings.tts_chunk_timeout_seconds,
        overall_timeout_seconds=settings.tts_overall_timeout_seconds,
        temp_dir=settings.tts_temp_dir or None,
        cleanup_temp_files=settings.tts_cleanup_temp_files,
    )
    synth_semaphore = None
    if settings.local_tts_strict_mode or tts_provider.is_local:
        synth_semaphore = _tts_synth_semaphore
    return TTSPipeline(
        provider=tts_provider,
        config=config,
        progress_callback=progress_callback,
        synth_semaphore=synth_semaphore,
        runtime_tracker=runtime_tracker,
    )


def _distinct_id(message: Message) -> str:
    user_id = message.from_user.id if message.from_user else 0
    return str(user_id)


async def _acquire_tts_job_slot(
    status_message: Message | None,
    message: Message,
) -> Message | None:
    if _tts_job_semaphore.locked():
        status_message = await safe_update_status(
            status_message=status_message,
            text=(
                "Ожидаю свободный слот TTS на сервере... "
                f"Активных задач: {runtime_tracker.active_jobs}."
            ),
            fallback_message_source=message,
        )
    await _tts_job_semaphore.acquire()
    return status_message


def _release_tts_job_slot() -> None:
    _tts_job_semaphore.release()


def _source_from_start(text: str | None) -> str | None:
    if not text:
        return None
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return None
    return parts[1].strip() or None


@dp.message(CommandStart())
async def handle_start(message: Message) -> None:
    await with_telegram_retries(
        lambda: message.answer(
            "Привет! Пришли текст, ссылку на статью или PDF. "
            "Я сгенерирую аудио для прослушивания."
        ),
        retries=settings.telegram_api_retries,
    )
    await event_logger.capture(
        event="bot_started",
        distinct_id=_distinct_id(message),
        properties={"source": _source_from_start(message.text)},
    )


@dp.message(F.document)
async def handle_document(message: Message, bot: Bot) -> None:
    document = message.document
    if document is None:
        await with_telegram_retries(
            lambda: message.answer("Не удалось прочитать документ."),
            retries=settings.telegram_api_retries,
        )
        await event_logger.capture(
            event="error_occurred",
            distinct_id=_distinct_id(message),
            properties={"error_type": "DocumentMissing", "step": "document_validation"},
        )
        return

    if not document.file_name or not document.file_name.lower().endswith(".pdf"):
        await with_telegram_retries(
            lambda: message.answer("Сейчас поддерживается только PDF."),
            retries=settings.telegram_api_retries,
        )
        await event_logger.capture(
            event="error_occurred",
            distinct_id=_distinct_id(message),
            properties={
                "error_type": "UnsupportedDocumentType",
                "step": "document_validation",
            },
        )
        return

    await event_logger.capture(
        event="document_uploaded",
        distinct_id=_distinct_id(message),
        properties={
            "file_type": "pdf",
            "file_size_kb": round((document.file_size or 0) / 1024, 2),
            "source": _source_from_start(message.caption),
        },
    )

    status = await with_telegram_retries(
        lambda: message.answer("Скачиваю PDF и готовлю аудио..."),
        retries=settings.telegram_api_retries,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / document.file_name
        await bot.download(document, destination=pdf_path)
        await _generate_and_send_audio(
            message=message,
            status_message=status,
            raw_text=message.caption,
            pdf_path=pdf_path,
        )


@dp.message(F.text)
async def handle_text(message: Message) -> None:
    maybe_url = extract_url(message.text or "")
    if maybe_url:
        user_id = message.from_user.id if message.from_user else 0
        _pending_url_by_user[user_id] = maybe_url
        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=label)] for label in MODE_BUTTON_TO_VALUE],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        await with_telegram_retries(
            lambda: message.answer(
                "Выбери режим обработки ссылки:\n"
                "🧾 Близко к оригиналу\n"
                "🎧 Под слух\n"
                "⚡ Коротко под слух",
                reply_markup=keyboard,
            ),
            retries=settings.telegram_api_retries,
        )
        await event_logger.capture(
            event="link_submitted",
            distinct_id=_distinct_id(message),
            properties={"source": _source_from_start(message.text)},
        )
        return

    selected_mode_label = (message.text or "").strip()
    mode = MODE_BUTTON_TO_VALUE.get(
        selected_mode_label
    ) or LEGACY_MODE_BUTTON_TO_VALUE.get(selected_mode_label)
    if mode and message.from_user:
        pending_url = _pending_url_by_user.pop(message.from_user.id, None)
        if pending_url:
            status = await with_telegram_retries(
                lambda: message.answer(
                    "Извлекаю статью и синтезирую аудио...",
                    reply_markup=ReplyKeyboardRemove(),
                ),
                retries=settings.telegram_api_retries,
            )
            await _generate_and_send_audio(
                message=message,
                status_message=status,
                raw_text=pending_url,
                pdf_path=None,
                url_mode=mode,
            )
            return

    status = await with_telegram_retries(
        lambda: message.answer("Готовлю текст и синтезирую аудио..."),
        retries=settings.telegram_api_retries,
    )
    await _generate_and_send_audio(
        message=message,
        status_message=status,
        raw_text=message.text,
        pdf_path=None,
        url_mode=MODE_CLOSE_TO_SOURCE,
    )


async def _generate_and_send_audio(
    message: Message,
    status_message: Message | None,
    raw_text: str | None,
    pdf_path: Path | None,
    url_mode: ArticleMode = MODE_CLOSE_TO_SOURCE,
) -> None:
    started_at = time.perf_counter()
    status_message = await _acquire_tts_job_slot(status_message, message)
    try:
        async with runtime_tracker.track_job():
            logger.info(
                "tts job started: active_jobs=%s active_synths=%s",
                runtime_tracker.active_jobs,
                runtime_tracker.active_synths,
            )
            maybe_url = extract_url(raw_text or "")
            if maybe_url and pdf_path is None:
                extraction_started_at = time.monotonic()
                logger.info(
                    "link pipeline extraction start: url=%s mode=%s",
                    maybe_url,
                    url_mode,
                )
                pipeline_result = await run_article_pipeline(
                    url=maybe_url,
                    mode=url_mode,
                    timeout_seconds=settings.request_timeout_seconds,
                    llm_service=llm_service,
                )
                logger.info(
                    "link pipeline extraction completed: url=%s mode=%s chars=%s duration_sec=%.3f",
                    maybe_url,
                    url_mode,
                    len(pipeline_result.text),
                    time.monotonic() - extraction_started_at,
                )
                text, input_was_truncated = _prepare_tts_input(pipeline_result.text)
                resolved_source = "url"
                await event_logger.capture(
                    event="url_pipeline_completed",
                    distinct_id=_distinct_id(message),
                    properties={
                        "mode": pipeline_result.mode,
                        "quality_score": pipeline_result.quality_report.quality_score,
                        "decision": pipeline_result.quality_report.decision,
                        "llm_used": pipeline_result.processing_trace.llm_used,
                        "flags": ",".join(pipeline_result.quality_report.flags),
                        "warnings": ",".join(pipeline_result.warnings),
                        "tts_input_truncated": input_was_truncated,
                    },
                )
            else:
                extraction_started_at = time.monotonic()
                logger.info("input resolve start: has_pdf=%s", bool(pdf_path))
                resolved = await resolve_input_text(
                    raw_text=raw_text,
                    pdf_local_path=pdf_path,
                    timeout_seconds=settings.request_timeout_seconds,
                )
                logger.info(
                    "input resolve completed: source=%s chars=%s duration_sec=%.3f",
                    resolved.source,
                    len(resolved.text),
                    time.monotonic() - extraction_started_at,
                )
                text, input_was_truncated = _prepare_tts_input(resolved.text)
                resolved_source = resolved.source

            if not text:
                status_message = await safe_update_status(
                    status_message=status_message,
                    text="Не удалось извлечь текст. Пришли другой источник.",
                    fallback_message_source=message,
                )
                await event_logger.capture(
                    event="error_occurred",
                    distinct_id=_distinct_id(message),
                    properties={
                        "error_type": "EmptyResolvedText",
                        "step": "extract_text",
                        "source": resolved_source,
                    },
                )
                return

            if resolved_source == "url":
                status_message = await safe_update_status(
                    status_message=status_message,
                    text="Отправляю текст статьи перед синтезом...",
                    fallback_message_source=message,
                )
                with tempfile.TemporaryDirectory() as tmpdir:
                    article_text_path = Path(tmpdir) / "article_tts_input.txt"
                    article_text_path.write_text(text, encoding="utf-8")
                    await with_telegram_retries(
                        lambda: message.answer_document(
                            document=FSInputFile(article_text_path),
                            caption="Текст, который отправляю в синтез.",
                        ),
                        retries=settings.telegram_api_retries,
                    )

            await event_logger.capture(
                event="audio_generation_started",
                distinct_id=_distinct_id(message),
                properties={
                    "char_count": len(text),
                    "source": resolved_source,
                    "tts_input_truncated": input_was_truncated,
                    "active_jobs": runtime_tracker.active_jobs,
                    "active_synths": runtime_tracker.active_synths,
                },
            )

            with tempfile.TemporaryDirectory() as tmpdir:
                out_path = Path(tmpdir) / "speech.mp3"

                async def _on_tts_progress(event: TTSProgressEvent) -> None:
                    nonlocal status_message
                    status_message = await safe_update_status(
                        status_message=status_message,
                        text=event.message,
                        fallback_message_source=message,
                    )

                pipeline = _make_tts_pipeline(progress_callback=_on_tts_progress)

                logger.info(
                    "tts pipeline start: source=%s text_chars=%s chunk_char_limit=%s sentence_limit=%s word_limit=%s active_jobs=%s active_synths=%s",
                    resolved_source,
                    len(text),
                    settings.max_chars_per_chunk,
                    settings.max_sentences_per_chunk,
                    settings.max_words_per_chunk,
                    runtime_tracker.active_jobs,
                    runtime_tracker.active_synths,
                )
                try:
                    chunk_paths = await pipeline.synthesize_to_file(text, out_path)
                except ValueError:
                    status_message = await safe_update_status(
                        status_message=status_message,
                        text="Текст пустой после обработки.",
                        fallback_message_source=message,
                    )
                    await event_logger.capture(
                        event="error_occurred",
                        distinct_id=_distinct_id(message),
                        properties={
                            "error_type": "EmptyChunks",
                            "step": "split_text",
                            "source": resolved_source,
                        },
                    )
                    return
                output_size = out_path.stat().st_size
                logger.info(
                    "tts completed: chunks=%s output_bytes=%s active_jobs=%s active_synths=%s",
                    len(chunk_paths),
                    output_size,
                    runtime_tracker.active_jobs,
                    runtime_tracker.active_synths,
                )
                status_message = await safe_update_status(
                    status_message=status_message,
                    text="Отправляю аудио в Telegram...",
                    fallback_message_source=message,
                )
                logger.info(
                    "telegram send audio start: output_bytes=%s source=%s",
                    output_size,
                    resolved_source,
                )
                try:
                    await with_telegram_retries(
                        lambda: _run_with_timeout(
                            message.answer_audio(
                                audio=FSInputFile(out_path),
                                caption=(
                                    "Готово. Источник: "
                                    f"{resolved_source}. Длина текста: {len(text)} символов."
                                ),
                            ),
                            timeout_seconds=settings.telegram_api_timeout_seconds,
                            step="send_audio",
                        ),
                        retries=settings.telegram_api_retries,
                    )
                except Exception:
                    logger.exception(
                        "telegram send audio failed: output_bytes=%s source=%s",
                        output_size,
                        resolved_source,
                    )
                    raise
                logger.info(
                    "telegram send audio completed: output_bytes=%s",
                    output_size,
                )
            processing_time = round(time.perf_counter() - started_at, 3)

            await event_logger.capture(
                event="audio_generated",
                distinct_id=_distinct_id(message),
                properties={
                    "duration_sec": 0,
                    "char_count": len(text),
                    "processing_time_sec": processing_time,
                    "source": resolved_source,
                    "active_jobs": runtime_tracker.active_jobs,
                    "active_synths": runtime_tracker.active_synths,
                },
            )
            if resolved_source == "url":
                await event_logger.capture(
                    event="llm output_sent_to_tts",
                    distinct_id=_distinct_id(message),
                    properties={
                        "flow": "article_to_tts",
                        "source_type": "url",
                        "char_count": len(text),
                    },
                )

            await event_logger.capture(
                event="audio_downloaded",
                distinct_id=_distinct_id(message),
                properties={"source": resolved_source},
            )

            if status_message:
                await with_telegram_retries(
                    lambda: status_message.delete(),
                    retries=settings.telegram_api_retries,
                )
            logger.info(
                "pipeline completed successfully: source=%s chars=%s chunks=%s duration_sec=%.3f active_jobs=%s active_synths=%s",
                resolved_source,
                len(text),
                len(chunk_paths),
                time.perf_counter() - started_at,
                runtime_tracker.active_jobs,
                runtime_tracker.active_synths,
            )
    except Exception as exc:
        logger.exception("Failed to generate audio")
        error_text = (
            exc.user_message
            if hasattr(exc, "user_message")
            else f"Ошибка: {type(exc).__name__}: {exc}"
        )
        await event_logger.capture(
            event="error_occurred",
            distinct_id=_distinct_id(message),
            properties={
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "step": getattr(exc, "step", "pipeline"),
                "active_jobs": runtime_tracker.active_jobs,
                "active_synths": runtime_tracker.active_synths,
            },
        )
        await safe_update_status(
            status_message=status_message,
            text=error_text,
            fallback_message_source=message,
        )
    finally:
        _release_tts_job_slot()


async def main() -> None:
    if not settings.telegram_bot_token or ":" not in settings.telegram_bot_token:
        raise ValueError("Некорректный TELEGRAM_BOT_TOKEN")

    try:
        await tts_provider.preload()
    except Exception as exc:
        logger.warning("TTS preload error: %s: %s", type(exc).__name__, exc)

    session = AiohttpSession(timeout=settings.telegram_api_timeout_seconds)
    bot = Bot(token=settings.telegram_bot_token, session=session)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
