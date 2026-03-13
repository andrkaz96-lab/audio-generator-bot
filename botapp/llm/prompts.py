from __future__ import annotations

from dataclasses import dataclass

MODE_CLOSE_TO_SOURCE = "close_to_source"
MODE_AUDIO_ADAPTED = "audio_adapted"
MODE_AUDIO_SUMMARY = "audio_summary"

MODE_ALIASES: dict[str, str] = {
    "near_verbatim": MODE_CLOSE_TO_SOURCE,
    "readable_cleaned": MODE_AUDIO_ADAPTED,
    MODE_CLOSE_TO_SOURCE: MODE_CLOSE_TO_SOURCE,
    MODE_AUDIO_ADAPTED: MODE_AUDIO_ADAPTED,
    MODE_AUDIO_SUMMARY: MODE_AUDIO_SUMMARY,
}

SYSTEM_PROMPT_CLOSE_TO_SOURCE = (
    "Ты выполняешь очистку текста статьи в режиме close_to_source. "
    "Это НЕ суммаризация и НЕ творческий пересказ.\n"
    "1) Верни только plain text без markdown и комментариев.\n"
    "2) Формат: заголовок, пустая строка, полный текст.\n"
    "3) Сохрани порядок, факты, цитаты и лексику максимально близко к оригиналу.\n"
    "4) Удали веб-мусор, технические артефакты и emoji.\n"
    "5) Преобразуй списки в звучащие перечни без потери порядка.\n"
    "6) Нельзя добавлять новые факты и нельзя сокращать до summary."
)

SYSTEM_PROMPT_AUDIO_ADAPTED = (
    "Ты адаптируешь статью для прослушивания в режиме audio_adapted. "
    "Это НЕ дословное чтение и НЕ свободный пересказ.\n"
    "1) Работай только на основе предоставленного заголовка и текста статьи.\n"
    "2) Нельзя добавлять новые факты, выводы, цитаты, цифры, даты и внешний контекст.\n"
    "3) Если факт не подтверждается исходником — опусти его.\n"
    "4) Можно менять структуру, объединять и сокращать фрагменты для линейного восприятия на слух.\n"
    "5) Пиши короткими предложениями: одна мысль на предложение.\n"
    "6) Убирай визуальный синтаксис, веб-мусор и emoji.\n"
    "7) Верни только plain text в формате: заголовок, пустая строка, итоговый текст.\n"
    "8) Цель: итоговая дорожка не длиннее 15 минут."
)

SYSTEM_PROMPT_AUDIO_SUMMARY = (
    "Ты делаешь краткую аудио-версию статьи в режиме audio_summary.\n"
    "1) Это НЕ свободный пересказ и НЕ добавление новых фактов.\n"
    "2) Опирайся только на исходный заголовок и текст статьи.\n"
    "3) Оставь только ключевые мысли, убери второстепенные детали.\n"
    "4) Пиши короткими предложениями: одна мысль на предложение.\n"
    "5) Убирай все, что мешает восприятию на слух, включая emoji и визуальный синтаксис.\n"
    "6) Если факт не подтверждается источником — опусти его.\n"
    "7) Верни только plain text в формате: заголовок, пустая строка, итоговый текст.\n"
    "8) Цель: итоговая дорожка не длиннее 3 минут."
)

SYSTEM_PROMPT_VERIFIER = (
    "Ты проверяешь draft аудио-текста на соответствие source text.\n"
    "Нельзя допускать неподтвержденные факты.\n"
    'Верни только JSON: {"decision":"pass|repair|fail","notes":"...","repaired_text":"..."}.\n'
    "repair: перепиши консервативно, удалив неподтвержденные утверждения; без новых фактов."
)


@dataclass(frozen=True)
class PromptContext:
    mode: str
    source_url: str | None
    title: str | None
    body_text: str
    target_duration_sec: int | None = None
    hard_cap_sec: int | None = None
    word_budget: int | None = None


def canonical_mode(mode: str) -> str:
    return MODE_ALIASES.get(mode, MODE_CLOSE_TO_SOURCE)


def system_prompt_for_mode(mode: str) -> str:
    resolved = canonical_mode(mode)
    if resolved == MODE_AUDIO_SUMMARY:
        return SYSTEM_PROMPT_AUDIO_SUMMARY
    if resolved == MODE_AUDIO_ADAPTED:
        return SYSTEM_PROMPT_AUDIO_ADAPTED
    return SYSTEM_PROMPT_CLOSE_TO_SOURCE


def build_user_prompt(*, context: PromptContext) -> str:
    safe_title = (context.title or "").strip() or "[MISSING_TITLE]"
    source_part = context.source_url.strip() if context.source_url else "unknown"
    extra = ""
    if context.target_duration_sec is not None:
        extra += f"\nЦелевая длительность (сек): {context.target_duration_sec}"
    if context.hard_cap_sec is not None:
        extra += f"\nЖесткий лимит (сек): {context.hard_cap_sec}"
    if context.word_budget is not None:
        extra += f"\nРекомендуемый бюджет слов: {context.word_budget}"
    return (
        f"Режим: {canonical_mode(context.mode)}\n"
        "Источник URL: "
        f"{source_part}\n"
        f"{extra}\n\n"
        "Заголовок (из extractor):\n"
        f"{safe_title}\n\n"
        "Основной текст статьи (из extractor, полный):\n"
        f"{context.body_text.strip()}"
    )


def build_verifier_prompt(
    *, source_title: str | None, source_body: str, draft_text: str
) -> str:
    safe_title = (source_title or "").strip() or "[MISSING_TITLE]"
    return (
        "SOURCE TITLE:\n"
        f"{safe_title}\n\n"
        "SOURCE BODY:\n"
        f"{source_body.strip()}\n\n"
        "DRAFT AUDIO SCRIPT:\n"
        f"{draft_text.strip()}"
    )
