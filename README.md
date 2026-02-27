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
- `POSTHOG_API_KEY` — Project API Key (формат `phc_...`)
- `POSTHOG_PROJECT_ID` — ID проекта PostHog
- `POSTHOG_HOST` — хост PostHog (обычно `https://app.posthog.com`)
- `ANALYTICS_ENABLED` — включить аналитику (`true`/`false`)

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


## Обновление бота на Yandex Cloud (VM + systemd)

Ниже — подробная, практическая инструкция именно для вашего кейса:
- VM доступна по SSH: `ssh -l ubuntu 10.130.0.29`
- репозиторий: `https://sourcecraft.dev/andrkaz96/audio-generator-bot`
- `TELEGRAM_BOT_TOKEN` у вас уже есть

### Шаг 0. Что должно быть заранее

На VM должны быть установлены:
- `git`
- `python3` и `python3-venv`
- `systemd` (обычно есть на Ubuntu)

Проверка:

```bash
git --version
python3 --version
systemctl --version
```

Если чего-то нет:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv
```

### Шаг 1. Подключиться к VM

С вашего локального компьютера:

```bash
ssh -l ubuntu 10.130.0.29
```

Что делает команда: открывает SSH-сессию на вашей виртуальной машине под пользователем `ubuntu`.

### Шаг 2. Найти папку, где уже развернут бот

На VM выполните:

```bash
find /opt /home -maxdepth 3 -type d -name ".git" 2>/dev/null
```

Что делает команда: ищет git-репозитории в типовых каталогах.

Если репозиторий еще не клонирован, разверните его (пример):

```bash
sudo mkdir -p /opt/audio-generator-bot
sudo chown -R "$USER":"$USER" /opt/audio-generator-bot
git clone https://sourcecraft.dev/andrkaz96/audio-generator-bot /opt/audio-generator-bot
```

> Если репозиторий приватный и попросит логин/пароль, используйте PAT (Personal Access Token) sourcecraft вместо пароля.

### Шаг 3. Проверить `.env` (самое важное)

Перейдите в папку бота и откройте `.env`:

```bash
cd /opt/audio-generator-bot
nano .env
```

Минимум должно быть:

```env
TELEGRAM_BOT_TOKEN=<ваш_токен>
TTS_PROVIDER=silero
```

Где взять токен, если понадобится заново:
- открыть `@BotFather` в Telegram
- выбрать бота → `/token`
- скопировать новый токен

### Шаг 4. Узнать имя systemd-сервиса бота

Если имя сервиса не помните:

```bash
systemctl list-units --type=service | grep -i bot
```

Часто это что-то вроде `tg-audio-bot.service`.

### Шаг 5. Обновить бота до актуального кода из Git

В репозитории запустите скрипт:

```bash
cd /opt/audio-generator-bot
chmod +x ./scripts_update_yc_vm.sh
./scripts_update_yc_vm.sh /opt/audio-generator-bot tg-audio-bot main
```

Что делает скрипт:
- `git fetch --all --prune`
- переключает на нужную ветку
- делает `git pull --ff-only`
- проверяет/создает `.venv`
- обновляет `pip`
- ставит зависимости `pip install -r requirements.txt`
- перезапускает systemd-сервис
- показывает статус сервиса

### Шаг 6. Проверка после обновления

На VM:

```bash
sudo systemctl status tg-audio-bot --no-pager -l
journalctl -u tg-audio-bot -n 100 --no-pager
```

В Telegram:
- отправить `/start`
- отправить короткий текст
- убедиться, что приходит `mp3`

### Какие доступы нужны от вас (если подключаюсь/помогаю удаленно)

- SSH-доступ к VM (`ubuntu@10.130.0.29`)
- пользователь с правом `sudo systemctl restart <service>`
- доступ VM к приватному репозиторию (PAT/Deploy key)
- ваш `TELEGRAM_BOT_TOKEN` в `.env`

### Частые ошибки

- `Permission denied (publickey)` при SSH
  - не добавлен ваш SSH-ключ в VM
- `fatal: Authentication failed` при `git pull`
  - нет/просрочен PAT или не настроен deploy key
- сервис не стартует после обновления
  - проверьте логи через `journalctl -u <service> -n 200 --no-pager`


## Продуктовая аналитика (PostHog)

В боте добавлен `event_logger`, который отправляет продуктовые события в PostHog.

События MVP:
- `bot_started`
- `document_uploaded`
- `link_submitted`
- `audio_generation_started`
- `audio_generated`
- `audio_downloaded`
- `error_occurred`
- `subscription_started` (зарезервировано на будущее)

Обязательные принципы:
- `distinct_id = telegram user_id`
- не отправляем персональные данные
- не отправляем текст документов/сообщений
- события отправляются как отдельные атомарные capture-события

### Быстрая настройка

1. В `.env` добавить:

```env
POSTHOG_API_KEY=phc_QULeOM973qkka9xUzmJZMhMiq7VBNIF4x167Up2YdQ2
POSTHOG_PROJECT_ID=326507
POSTHOG_HOST=https://app.posthog.com
ANALYTICS_ENABLED=true
```

2. Перезапустить бота.
3. Проверить в PostHog, что появляются события.

### Свойства событий

Для всех событий отправляются:
- `platform=telegram`
- `source` (если есть)
- `distinct_id` (как `user_id` Telegram)

Дополнительно:
- `document_uploaded`: `file_type`, `file_size_kb`
- `audio_generated`: `duration_sec`, `char_count`, `processing_time_sec`
- `error_occurred`: `error_type`, `step`
