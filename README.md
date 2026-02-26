# Telegram TTS Bot (local MVP)

Локальный Telegram-бот на Python, который принимает вход в одном из форматов:
- обычный текст
- ссылка на статью
- PDF-файл (документом в чат)
- ссылка на PDF

На выходе бот отправляет `mp3`-аудио, пригодное для прослушивания в дороге.

## Текущий статус

- Основной TTS: `silero` (open-source, локально на CPU)
- Авто-fallback: `gtts`, если `silero` недоступен (например, временно не скачались веса)
- Telegram API: увеличенный timeout + retry
- Yandex SpeechKit: пока заглушка (подключается после передачи кредов)

## Архитектура решения

1. Telegram update приходит в `botapp.main`.
2. Определяется источник текста: `text` / `url` / `pdf`.
3. Текст нормализуется и режется на чанки.
4. Для каждого чанка вызывается TTS-провайдер.
5. Аудио-чанки склеиваются и отправляются пользователю как `mp3`.

## Ключевые компоненты и функции

### Оркестрация бота

- `botapp/main.py`
- `main()`
  - создает `Bot` и запускает polling
- `handle_start()`
  - обработчик `/start`
- `handle_document()`
  - обработка PDF-документа из Telegram
- `handle_text()`
  - обработка текстового сообщения
- `_generate_and_send_audio()`
  - общий pipeline: извлечение текста -> чанки -> синтез -> отправка аудио
- `with_telegram_retries()`
  - retry-обертка для вызовов Telegram API при сетевых сбоях

### Конфигурация

- `botapp/config.py`
- `Settings`
  - единая структура всех runtime-параметров
- `load_settings()`
  - загрузка и валидация env-переменных

### Извлечение текста

- `botapp/extractors/input_resolver.py`
- `resolve_input_text()`
  - выбирает стратегию извлечения в зависимости от входа

- `botapp/extractors/url_text.py`
- `extract_url()`
  - достает URL из сообщения
- `fetch_article_text()`
  - загружает HTML и извлекает основной текст статьи

- `botapp/extractors/pdf_text.py`
- `extract_pdf_text_from_file()`
  - извлечение текста из PDF-файла
- `extract_pdf_text_from_url()`
  - скачивание PDF по URL + извлечение
- `extract_pdf_text_from_bytes()`
  - извлечение из байтов PDF

### Обработка текста

- `botapp/utils/text.py`
- `normalize_text()`
  - чистит лишние пробелы
- `split_text_into_chunks()`
  - делит длинный текст на чанки по `MAX_CHARS_PER_CHUNK`

### TTS-слой

- `botapp/tts/base.py`
- `TTSProvider.synthesize()`
  - единый интерфейс для всех движков

- `botapp/tts/factory.py`
- `make_tts_provider()`
  - создает нужный провайдер по `TTS_PROVIDER`

- `botapp/tts/silero_provider.py`
- `SileroTTSProvider.synthesize()`
  - локальный синтез через Silero
- `_ensure_model_loaded()`
  - lazy-загрузка модели
- `_split_text()`
  - внутренняя нарезка для ограничения Silero (~900 символов за вызов)
- `_encode_mp3()`
  - кодирование PCM в MP3

- `botapp/tts/fallback_provider.py`
- `FallbackTTSProvider.synthesize()`
  - при ошибке primary-провайдера переключает на fallback

- `botapp/tts/gtts_provider.py`
- `GTTSProvider.synthesize()`
  - fallback-синтез через gTTS

- `botapp/tts/edge_provider.py`
- `EdgeTTSProvider.synthesize()`
  - альтернативный TTS через Edge (может давать 403)

- `botapp/tts/yandex_provider.py`
- `YandexSpeechKitProvider`
  - заглушка до подключения облачных кредов

## Быстрый старт

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

Заполнить минимум:
- `TELEGRAM_BOT_TOKEN=...`
- `TTS_PROVIDER=silero`

Запуск:

```bash
source .venv/bin/activate
python -m botapp.main
```

## .env параметры

- `TELEGRAM_BOT_TOKEN` — токен Telegram-бота
- `TTS_PROVIDER` — `silero` | `gtts` | `edge` | `yandex`
- `SILERO_SPEAKER` — голос Silero (`xenia`, `baya`, `aidar`, `kseniya`, `eugene`)
- `SILERO_SAMPLE_RATE` — sample rate (по умолчанию `48000`)
- `SILERO_MODEL_LANGUAGE` — язык модели (`ru`)
- `SILERO_MODEL_SPEAKER` — модель (`v4_ru`)
- `GTTS_LANG` — язык для gTTS (`ru`)
- `EDGE_VOICE` — голос Edge TTS
- `MAX_CHARS_PER_CHUNK` — размер чанка на уровне pipeline (по умолчанию `4000`)
- `MAX_INPUT_CHARS` — общий лимит входного текста
- `REQUEST_TIMEOUT_SECONDS` — timeout HTTP-запросов для URL/PDF
- `TELEGRAM_API_TIMEOUT_SECONDS` — timeout Telegram API
- `TELEGRAM_API_RETRIES` — число retries Telegram API

## Важные технические нюансы

- Silero может падать на очень длинных строках за один вызов. В провайдере это уже учтено внутренним `_split_text()`.
- При ошибке загрузки/работы Silero автоматически включается `gtts` fallback.
- Первый запуск Silero может быть дольше из-за загрузки весов.

## Диагностика типовых проблем

- `TokenValidationError`
  - проверь формат `TELEGRAM_BOT_TOKEN` (должен содержать `:`)
- `TelegramNetworkError: Request timeout error`
  - увеличь `TELEGRAM_API_TIMEOUT_SECONDS` и `TELEGRAM_API_RETRIES`
- `HTTPError 503` при загрузке Silero
  - временная проблема внешнего хоста; бот должен переключиться на `gtts`
- `ModuleNotFoundError`
  - выполнить `pip install -r requirements.txt` в активированном `.venv`

## Следующий этап

После передачи кредов добавляем полноценный `YandexSpeechKitProvider` и готовим деплой в Yandex Cloud.
