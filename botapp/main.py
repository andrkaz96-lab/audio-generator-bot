from __future__ import annotations

import asyncio
import logging
import tempfile
from typing import Awaitable, Callable, TypeVar
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, Message

from botapp.config import load_settings
from botapp.extractors.input_resolver import resolve_input_text
from botapp.tts.factory import make_tts_provider
from botapp.utils.text import split_text_into_chunks


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


settings = load_settings()
tts_provider = make_tts_provider(settings)

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


@dp.message(CommandStart())
async def handle_start(message: Message) -> None:
    await with_telegram_retries(
        lambda: message.answer(
        "Привет! Пришли текст, ссылку на статью или PDF. "
        "Я сгенерирую аудио для прослушивания."
    ),
        retries=settings.telegram_api_retries,
    )


@dp.message(F.document)
async def handle_document(message: Message, bot: Bot) -> None:
    document = message.document
    if document is None:
        await with_telegram_retries(
            lambda: message.answer("Не удалось прочитать документ."),
            retries=settings.telegram_api_retries,
        )
        return

    if not document.file_name or not document.file_name.lower().endswith(".pdf"):
        await with_telegram_retries(
            lambda: message.answer("Сейчас поддерживается только PDF."),
            retries=settings.telegram_api_retries,
        )
        return

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
    try:
        resolved = await resolve_input_text(
            raw_text=raw_text,
            pdf_local_path=pdf_path,
            timeout_seconds=settings.request_timeout_seconds,
        )

        text = resolved.text[: settings.max_input_chars]
        if not text:
            await with_telegram_retries(
                lambda: status_message.edit_text("Не удалось извлечь текст. Пришли другой источник."),
                retries=settings.telegram_api_retries,
            )
            return

        chunks = split_text_into_chunks(text, settings.max_chars_per_chunk)
        if not chunks:
            await with_telegram_retries(
                lambda: status_message.edit_text("Текст пустой после обработки."),
                retries=settings.telegram_api_retries,
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

        await with_telegram_retries(
            lambda: status_message.delete(),
            retries=settings.telegram_api_retries,
        )

    except Exception as exc:
        logger.exception("Failed to generate audio")
        await with_telegram_retries(
            lambda: status_message.edit_text(f"Ошибка: {type(exc).__name__}: {exc}"),
            retries=settings.telegram_api_retries,
        )


async def main() -> None:
    session = AiohttpSession(timeout=float(settings.telegram_api_timeout_seconds))
    bot = Bot(token=settings.telegram_bot_token, session=session)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
