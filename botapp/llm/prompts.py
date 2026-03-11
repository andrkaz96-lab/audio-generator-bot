from __future__ import annotations

SYSTEM_PROMPT_NEAR_VERBATIM = (
    "Ты выполняешь near-verbatim очистку текста статьи. "
    "Это НЕ суммаризация и НЕ творческий пересказ.\n"
    "1) Верни только plain text без markdown и комментариев.\n"
    "2) Формат: заголовок, пустая строка, полный текст.\n"
    "3) Сохрани порядок, факты, цитаты и лексику максимально близко к оригиналу.\n"
    "4) Разрешено удалять только веб-мусор и технические артефакты.\n"
    "5) Нельзя добавлять новые факты и нельзя сокращать до summary."
)

SYSTEM_PROMPT_READABLE_CLEANED = (
    "Ты выполняешь readable-cleaned очистку для озвучки. "
    "Это НЕ суммаризация и НЕ добавление новых фактов.\n"
    "1) Верни только plain text без markdown и комментариев.\n"
    "2) Формат: заголовок, пустая строка, полный текст.\n"
    "3) Сохрани все тезисы и порядок изложения.\n"
    "4) Можно мягко адаптировать фразы, которые плохо звучат в аудио.\n"
    "5) Нельзя искажать смысл, тон и фактуру статьи."
)


def system_prompt_for_mode(mode: str) -> str:
    if mode == "readable_cleaned":
        return SYSTEM_PROMPT_READABLE_CLEANED
    return SYSTEM_PROMPT_NEAR_VERBATIM


def build_user_prompt(*, title: str | None, body_text: str, source_url: str | None, mode: str) -> str:
    safe_title = (title or "").strip() or "[MISSING_TITLE]"
    source_part = source_url.strip() if source_url else "unknown"
    return (
        f"Режим: {mode}\n"
        "Источник URL: "
        f"{source_part}\n\n"
        "Заголовок (из extractor):\n"
        f"{safe_title}\n\n"
        "Основной текст статьи (из extractor, полный):\n"
        f"{body_text.strip()}"
    )
