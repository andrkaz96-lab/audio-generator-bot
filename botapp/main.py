from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import time
from pathlib import Path
from typing import Awaitable, Callable, TypeVar

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, Message

from botapp.analytics import EventLogger
from botapp.config import load_settings
from botapp.extractors.input_resolver import resolve_input_text
from botapp.extractors.url_text import extract_url
from botapp.llm.service import ArticleLLMService
from botapp.llm.yandex_client import YandexLLMClient
from botapp.tts.factory import make_tts_provider
from botapp.utils.text import split_text_into_chunks


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


async def with_telegram_retries(operation: Callable[[], Awaitable[T]], retries: int) -> T:
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


def _distinct_id(message: Message) -> str:
    user_id = message.from_user.id if message.from_user else 0
    return str(user_id)


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
            properties={"error_type": "UnsupportedDocumentType", "step": "document_validation"},
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
        await event_logger.capture(
            event="link_submitted",
            distinct_id=_distinct_id(message),
            properties={"source": _source_from_start(message.text)},
        )

    status = await with_telegram_retries(
        lambda: message.answer("Готовлю текст и синтезирую аудио..."),
        retries=settings.telegram_api_retries,
    )
    await _generate_and_send_audio(
        message=message,
        status_message=status,
        raw_text=message.text,
        pdf_path=None,
    )


async def _generate_and_send_audio(
    message: Message,
    status_message: Message,
    raw_text: str | None,
    pdf_path: Path | None,
) -> None:
    started_at = time.perf_counter()
    try:
        resolved = await resolve_input_text(
            raw_text=raw_text,
            pdf_local_path=pdf_path,
            timeout_seconds=settings.request_timeout_seconds,
        )

        text = resolved.text[: settings.max_input_chars]
        if resolved.source == "url":
            await event_logger.capture(
                event="llm request_sent",
                distinct_id=_distinct_id(message),
                properties={"flow": "article_to_tts", "source_type": "url", "provider": settings.llm_provider},
            )
            result = await llm_service.build_tts_text_for_article(
                title=resolved.title,
                body_text=resolved.body_text or text,
                source_url=resolved.source_url,
            )
            text = result.final_text
            analytics_payload = llm_service.analytics_properties(
                result=result,
                title=resolved.title,
                source_url=resolved.source_url,
                user_id=message.from_user.id if message.from_user else None,
                chat_id=message.chat.id if message.chat else None,
            )
            await event_logger.capture(
                event="llm response_received" if result.success else "llm request_failed",
                distinct_id=_distinct_id(message),
                properties=analytics_payload,
            )
            logger.info(
                json.dumps(
                    {
                        "event_name": "llm_article_processed",
                        "request_id": str(message.message_id),
                        "provider": result.provider,
                        "model_uri": result.model_uri,
                        "source_type": "url",
                        "source_url": resolved.source_url,
                        "user_id": message.from_user.id if message.from_user else None,
                        "chat_id": message.chat.id if message.chat else None,
                        "input_chars": result.input_chars,
                        "output_chars": result.output_chars,
                        "input_paragraphs": result.input_paragraphs,
                        "output_paragraphs": result.output_paragraphs,
                        "was_chunked": result.was_chunked,
                        "chunk_count": result.chunk_count,
                        "was_truncated": result.was_truncated,
                        "latency_ms": result.latency_ms,
                        "success": result.success,
                        "error_type": result.error_type,
                        "retry_count": result.retry_count,
                        "estimated_prompt_tokens": result.estimated_prompt_tokens,
                        "estimated_completion_tokens": result.estimated_completion_tokens,
                    },
                    ensure_ascii=False,
                )
            )

            if settings.llm_debug_send_text_file:
                with tempfile.TemporaryDirectory() as tmpdir:
                    name = f"article_tts_text_{message.message_id or int(time.time())}.txt"
                    text_path = Path(tmpdir) / name
                    text_path.write_text(text, encoding="utf-8")
                    await with_telegram_retries(
                        lambda: message.answer_document(document=FSInputFile(text_path), caption="Отладочный текст для TTS."),
                        retries=settings.telegram_api_retries,
                    )
                await event_logger.capture(
                    event="llm debug_text_file_sent",
                    distinct_id=_distinct_id(message),
                    properties=analytics_payload,
                )

        if not text:
            await with_telegram_retries(
                lambda: status_message.edit_text("Не удалось извлечь текст. Пришли другой источник."),
                retries=settings.telegram_api_retries,
            )
            await event_logger.capture(
                event="error_occurred",
                distinct_id=_distinct_id(message),
                properties={"error_type": "EmptyResolvedText", "step": "extract_text", "source": resolved.source},
            )
            return

        await event_logger.capture(
            event="audio_generation_started",
            distinct_id=_distinct_id(message),
            properties={"char_count": len(text), "source": resolved.source},
        )

        chunks = split_text_into_chunks(text, settings.max_chars_per_chunk)
        if not chunks:
            await with_telegram_retries(
                lambda: status_message.edit_text("Текст пустой после обработки."),
                retries=settings.telegram_api_retries,
            )
            await event_logger.capture(
                event="error_occurred",
                distinct_id=_distinct_id(message),
                properties={"error_type": "EmptyChunks", "step": "split_text", "source": resolved.source},
            )
            return

        audio_parts: list[bytes] = []
        for idx, chunk in enumerate(chunks, start=1):
            await with_telegram_retries(
                lambda: status_message.edit_text(f"Синтез {idx}/{len(chunks)}..."),
                retries=settings.telegram_api_retries,
            )
            audio_parts.append(await tts_provider.synthesize(chunk))

        output = b"".join(audio_parts)
        processing_time = round(time.perf_counter() - started_at, 3)

        await event_logger.capture(
            event="audio_generated",
            distinct_id=_distinct_id(message),
            properties={
                "duration_sec": 0,
                "char_count": len(text),
                "processing_time_sec": processing_time,
                "source": resolved.source,
            },
        )
        if resolved.source == "url":
            await event_logger.capture(
                event="llm output_sent_to_tts",
                distinct_id=_distinct_id(message),
                properties={"flow": "article_to_tts", "source_type": "url", "char_count": len(text)},
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "speech.mp3"
            out_path.write_bytes(output)
            await with_telegram_retries(
                lambda: message.answer_audio(
                    audio=FSInputFile(out_path),
                    caption=f"Готово. Источник: {resolved.source}. Длина текста: {len(text)} символов.",
                ),
                retries=settings.telegram_api_retries,
            )

        await event_logger.capture(
            event="audio_downloaded",
            distinct_id=_distinct_id(message),
            properties={"source": resolved.source},
        )

        await with_telegram_retries(
            lambda: status_message.delete(),
            retries=settings.telegram_api_retries,
        )

    except Exception as exc:
        logger.exception("Failed to generate audio")
        error_text = f"Ошибка: {type(exc).__name__}: {exc}"
        await event_logger.capture(
            event="error_occurred",
            distinct_id=_distinct_id(message),
            properties={"error_type": type(exc).__name__, "step": "pipeline"},
        )
        await with_telegram_retries(
            lambda: status_message.edit_text(error_text),
            retries=settings.telegram_api_retries,
        )


async def main() -> None:
    if not settings.telegram_bot_token or ":" not in settings.telegram_bot_token:
        raise ValueError("Некорректный TELEGRAM_BOT_TOKEN")

    session = AiohttpSession(timeout=settings.telegram_api_timeout_seconds)
    bot = Bot(token=settings.telegram_bot_token, session=session)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
