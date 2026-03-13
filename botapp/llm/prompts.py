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
    "Ты создаешь audio_adapted: полноценную аудио-версию статьи для комфортного прослушивания. "
    "Это НЕ summary и НЕ агрессивное сжатие.\n"
    "1) Сохраняй почти весь смысл статьи: аргументы, объяснения, контекст и примеры.\n"
    "2) Допустима структурная переработка: упрощай синтаксис, дроби длинные фразы, сглаживай переходы между абзацами.\n"
    "3) Разрешено удалять только шум: веб-мусор, дубли, визуальные артефакты, технические блоки.\n"
    "4) Списки/таблицы преобразуй в связный звучащий текст без потери смысла и порядка.\n"
    "5) Нельзя добавлять новые факты, имена, цифры, даты, цитаты, причины/следствия и внешний контекст.\n"
    "6) Нельзя домысливать то, чего нет в источнике. Неподтвержденные утверждения удаляй.\n"
    "7) Пиши естественно для слуха: связный рассказ, ясные предложения, без телеграфного стиля.\n"
    "8) Верни только plain text: заголовок, пустая строка, затем итоговый текст."
)

SYSTEM_PROMPT_AUDIO_SUMMARY = (
    "Ты создаешь audio_summary: сокращенную, но связную аудио-версию статьи.\n"
    "1) Цель — передать ключевые идеи компактно, но как полноценный рассказ, а не список тезисов.\n"
    "2) Разрешено умеренное сокращение: убирай второстепенные детали, длинные отступления и повторения.\n"
    "3) Сохраняй основные мысли, причинно-следственные связи и важный контекст статьи.\n"
    "4) Можно переформулировать и перестраивать структуру для лучшего восприятия на слух.\n"
    "5) Нельзя добавлять новые факты, имена, цифры, даты, цитаты и внешний контекст.\n"
    "6) Нельзя домысливать; если утверждение не подтверждается источником, не включай его.\n"
    "7) Итог должен звучать естественно: связный, плавный и понятный текст для прослушивания.\n"
    "8) Верни только plain text: заголовок, пустая строка, затем итоговый текст."
)

SYSTEM_PROMPT_VERIFIER = (
    "Ты verifier. Сравнивай DRAFT только с SOURCE. Любой факт должен быть явно подтвержден SOURCE.\n"
    "Проверяй неподтвержденные: новые имена, числа, даты, цитаты, причинно-следственные выводы и конкретные утверждения.\n"
    "Если в DRAFT есть неподтвержденные фрагменты, выбери repair и удали/перепиши только эти фрагменты консервативно.\n"
    "Нельзя добавлять новые факты, внешний контекст, интерпретации или домыслы.\n"
    'Верни только JSON-объект формата: {"decision":"pass|repair|fail","reason":"...","unsupported_claims":["..."],"repaired_text":"..."}.\n'
    "Для pass: unsupported_claims пустой массив, repaired_text можно оставить пустым.\n"
    "Для repair: перечисли неподтвержденные утверждения и дай безопасный repaired_text.\n"
    "Для fail: укажи reason, почему проверка невозможна."
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
