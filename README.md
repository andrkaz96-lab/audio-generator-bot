# Telegram TTS Bot

Бот принимает текст, ссылку на статью или PDF и отправляет mp3.

## Что добавлено

Для URL-статей реализован гибридный пайплайн с двумя режимами:

- `near_verbatim` — максимально близко к оригиналу, только очистка от мусора.
- `readable_cleaned` — мягкая адаптация для восприятия и озвучки без изменения фактов.

Ключевой принцип: **extractor-first, LLM only when needed**.

---

## Как теперь работает обработка ссылок

### 1) Выбор режима в боте

Если пользователь отправляет ссылку, бот предлагает кнопки:

- `🧾 Почти дословно` (`near_verbatim`)
- `🎧 Чистый для озвучки` (`readable_cleaned`)

После выбора запускается обработка URL в выбранном режиме.

### 2) Гибридный pipeline

Порядок шагов:

1. `fetch page`
2. `rule-based extraction`
3. `quality evaluation`
4. `LLM fallback only if needed` (Yandex)
5. `separate TTS normalization`

### 3) Решения по режимам

- **Near-verbatim**:
  - LLM вызывается только при провале quality check.
  - Запрещены summary/пересказ/добавление фактов.

- **Readable-cleaned**:
  - При хорошем extraction допускается мягкий LLM cleanup.
  - Смысл, факты и порядок изложения сохраняются.

---

## Архитектурные модули

- `fetcher` — загрузка URL и метаданных страницы.
- `extractor` — выделение текстового контента статьи.
- `quality evaluator` — флаги качества и decision engine.
- `llm processor (Yandex)` — fallback/cleanup в строгом контракте.
- `tts normalizer` — отдельная нормализация под озвучку.
- `orchestrator` — управление шагами, trace, финальный результат.

---

## Quality layer (основные сигналы)

Оцениваются признаки плохого extraction:

- слишком короткий/слишком длинный текст,
- слишком много ссылок,
- мало абзацев,
- boilerplate-маркеры (cookie/share/subscribe и т.п.),
- низкое качество текста,
- mismatch title/body.

По итогам формируется:

- `quality_score`
- `flags[]`
- `decision`: `pass | pass_with_warnings | llm_fallback`

---

## Что логируется

- URL и домен,
- режим,
- quality score и flags,
- применялся ли LLM,
- длина итогового текста,
- предупреждения pipeline.

---

## Переменные `.env`

Обязательные:

- `TELEGRAM_BOT_TOKEN`

Для TTS:

- `TTS_PROVIDER`
- остальные параметры выбранного провайдера

Для LLM (Yandex):

- `LLM_ENABLED=true`
- `LLM_PROVIDER=yandex`
- `YANDEX_API_KEY=`
- `YANDEX_FOLDER_ID=`
- `YANDEX_API_BASE=https://llm.api.cloud.yandex.net/v1`
- `YANDEX_MODEL=yandexgpt-lite/latest` (конфиг-метка)
- `LLM_TIMEOUT_SECONDS=30`
- `LLM_MAX_INPUT_CHARS=18000`
- `LLM_DEBUG_SEND_TEXT_FILE=true`
- `LLM_LOG_PROMPTS=false`

Важно: в API передаётся `modelUri` вида:

`gpt://{YANDEX_FOLDER_ID}/yandexgpt-lite`

---

## Отладочный `.txt`

Если включён `LLM_DEBUG_SEND_TEXT_FILE=true`, бот отправляет `.txt` в UTF-8 с тем же текстом, который ушёл в TTS.

---

## Ограничения

- Оценка токенов — эвристическая.
- На сложной верстке extraction может требовать fallback.
- LLM ошибки не должны ломать весь pipeline: используется fallback-путь.

---

## Запуск

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m botapp.main
```
