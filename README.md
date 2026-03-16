# Telegram TTS Bot

Бот принимает текст, ссылку на статью или PDF и отправляет mp3.

## Что добавлено

Для URL-статей реализован гибридный пайплайн с тремя режимами:

- `close_to_source` (`near_verbatim` alias) — максимально близко к оригиналу, rule-based очистка + fallback LLM только при плохом extraction quality.
- `audio_adapted` (`readable_cleaned` alias) — полноценная адаптация под слух с обязательным LLM и verification/repair.
- `audio_summary` — краткая версия под слух с обязательным LLM и hard cap 3 минуты.

Ключевой принцип: **extractor-first, LLM only when needed**.

---

## Как теперь работает обработка ссылок

### 1) Выбор режима в боте

Если пользователь отправляет ссылку, бот предлагает кнопки:

- `🧾 Близко к оригиналу` (`close_to_source`)
- `🎧 Под слух` (`audio_adapted`)
- `⚡ Коротко под слух` (`audio_summary`)

После выбора запускается обработка URL в выбранном режиме.

### 2) Гибридный pipeline

Порядок шагов:

1. `fetch page`
2. `rule-based extraction`
3. `quality evaluation`
4. `mode-specific transform` (rule-based или LLM)
5. `verification/repair` для аудио-режимов
6. `shared TTS normalization + duration control`

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
- `LLM_TIMEOUT_SECONDS=30`
- `LLM_MAX_INPUT_CHARS=18000`
- `LLM_DEBUG_SEND_TEXT_FILE=true`
- `LLM_LOG_PROMPTS=false`

Важно: для OpenAI-compatible YandexGPT используется endpoint:

`POST https://llm.api.cloud.yandex.net/v1/chat/completions`

В API передаётся `model` вида:

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
pip install --no-cache-dir -r requirements.txt
python -m botapp.main
```



### Установка на CPU-only VM (без переполнения диска)

В `requirements.txt` уже зафиксирован CPU-only PyTorch для Linux (`torch==2.5.1+cpu`)
и добавлен индекс `https://download.pytorch.org/whl/cpu`, чтобы не подтягивались CUDA-пакеты.

Рекомендуемый порядок:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install --no-cache-dir -r requirements.txt
```

Если ранее была неудачная установка, очистите окружение перед повтором:

```bash
deactivate 2>/dev/null || true
rm -rf .venv ~/.cache/pip
```

## Надёжность TTS (Silero + fallback)

- Silero предзагружается на старте приложения (`tts_provider.preload()`), а не в момент пользовательского запроса.
- По умолчанию репозиторий модели хранится в `~/.cache/audio-generator-bot/silero-models` (можно переопределить `SILERO_REPO_DIR`).
- Если репозиторий отсутствует, он может быть скачан **один раз на старте** (`SILERO_ALLOW_DOWNLOAD_ON_STARTUP=true`).
- Во время обработки сообщений используется только уже загруженная модель; runtime-загрузка через `torch.hub` из сети не требуется.
- Если primary TTS падает, включается fallback-провайдер. Если fallback тоже недоступен — бот отправит понятную ошибку в чат.

### Полезные логи

LLM:
- `provider`, `base_url`, `endpoint`, `model_uri`, `status_code`, `success`, `latency_ms`, `error_body`.

TTS:
- `provider_name`, `fallback_provider_name`, `model_source`, `preload_success`, `error_type`, `error_message`.

### Быстрая проверка

1. Запустите бота и убедитесь, что в логах есть вызов:
   `https://llm.api.cloud.yandex.net/v1/chat/completions`
2. Убедитесь, что нет вызовов:
   `.../v1/completion`
3. Проверьте, что Silero preload происходит на старте, а не на первом пользовательском сообщении.
