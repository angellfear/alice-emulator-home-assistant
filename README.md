# Home Assistant — расширение эмулятора Алисы

Обсуждение и вопросы — в Telegram-группе [t.me/yandex_iot](https://t.me/yandex_iot).

Расширение подключает [Home Assistant](https://www.home-assistant.io/) к эмулятору
сервера Алисы частями — каждую можно включить отдельно:

| Часть | Что делает |
|---|---|
| Режим «Интеллекта» `home-assistant.ha` | фраза без сценария уходит conversation-агенту HA (`POST /api/conversation/process`), ответ — текст реплики; диалог колонки ведётся по `conversation_id` (SN) |
| Действие `ha.call_service` | вызов сервиса HA из сценария (`POST /api/services/<domain>/<service>`), имя объявлено в `permissions.actions` манифеста |
| Сценарий-пример `ha.light` | «включи свет на кухне» → `ha.call_service light.turn_on` (template-триггер hassil, таблица комнат → `light.kitchen` и т.д.) |
| Пресеты ASR/TTS `ha-asr` / `ha-tts` | распознавание и синтез через HA (`/api/stt/<провайдер>`, `/api/tts_get_url` → `/api/tts_proxy/…`) |
| Набор «Всё через Home Assistant» | кнопка в карточке расширения: пресеты ASR/TTS + режим одним кликом (`MODE.preset`) |
| MCP-сервер HA (`mcp/ha.json`) | интеграция «Model Context Protocol Server» для режима «AI агент» — управление домом инструментами; запись добавляется выключенной (токен вписывается отдельно) |

Весь конвейер «звук → текст → дом → звук» внутри HA не делается: теряются сценарии
эмулятора, звуковой кеш и самопроверка.

## Установка

- Вкладка «Расширения» эмулятора → источник — URL репозитория
  `https://github.com/angellfear/alice-emulator-home-assistant` (последний релиз; `…#<тег>` или
  `…#<коммит>` — закреплённая версия) или **локальная папка** (режим разработки, правки
  подхватываются).
- Требования (`extension.json`): эмулятор `>=0.1.0`, SDK `>=1.2.0 <2.0.0`
  (настройки в коде расширения — `ExtensionContext`). Дополнительных
  pip-пакетов нет: `aiohttp` уже входит в зависимости эмулятора.
- После установки расширение появляется во вкладке «Расширения» — там же его
  настройки. Самопроверка (папка `tests/` расширения) прогоняется через dry-run.

## Настройка

Настройки правятся во вкладке «Расширения» (манифест, `settings`):

| Поле | Значение |
|---|---|
| `url` | адрес HA, например `http://homeassistant.local:8123` |
| `token` | **долгоживущий токен доступа**: HA → профиль пользователя → «Безопасность» → «Долгоживущие токены доступа» → «Создать токен». Поддерживается ссылка `env:ИМЯ` — в настройке хранится имя переменной окружения (например `env:HA_TOKEN`), само значение живёт в окружении процесса эмулятора и в настройки/экспорты не попадает (как секреты провайдеров эмулятора) |
| `agent_id` | id агента Assist (необязательно), например `conversation.home_assistant` |
| `language` | язык фраз для HA, по умолчанию `ru` |

Код расширения читает эти значения штатно через `ExtensionContext`:
режим — `ctx.extension`, действие — `execution.extension`, адаптеры — аргумент
`extension=`; правка настроек действует со следующего вызова, рестарт не нужен.

Токен используется всеми частями: режимом и действием — из настроек расширения;
адаптерами — из поля `api_key` пресета (можно тоже `env:HA_TOKEN`), а пустой
`api_key` дополняется токеном из настроек расширения.

## Какие интеграции HA включить

| Интеграция HA | Зачем |
|---|---|
| **Assist / Conversation** | режим «Home Assistant»: conversation-агент (по умолчанию `conversation.home_assistant`) |
| **STT-провайдер** (Wyoming-Piper, Whisper и т.п.) | пресет `ha-asr`: URL вида `…/api/stt/stt.piper` — entity id провайдера в пути |
| **TTS-движок** (например `tts.piper`) | пресет `ha-tts`: поле `engine_id` = entity id движка |
| **Model Context Protocol Server** | MCP: URL `http://<ha>:8123/api/mcp`, заголовок `Authorization: Bearer <токен>` — впишите его в свою запись MCP (вкладка MCP эмулятора); `mcp/ha.json` расширения — выключенный шаблон |

## Эндпоинты HA: сверка с документацией (2026-10-31)

| Эндпоинт | В публичной документации | Источник правды |
|---|---|---|
| `POST /api/conversation/process` | **да** — REST API (developers.home-assistant.io → REST API, теперь contributors.home-assistant.io/core/internals/rest-api/) | поля тела: `text` (обязателен), `language`, `conversation_id`, `agent_id` — `homeassistant/components/conversation/http.py` |
| `POST /api/services/<domain>/<service>` | **да** — REST API | действие `ha.call_service` |
| `POST /api/stt/<provider>` | **нет** — эндпоинт внутренний, в REST-документации отсутствует | `homeassistant/components/stt/__init__.py` (`SpeechToTextView`): метаданные в заголовке `X-Speech-Content`, шесть обязательных полей `language, format, codec, bit_rate, sample_rate, channel` (сверено с `_metadata_from_header`); ответ `{"text", "result"}` |
| `POST /api/tts_get_url` | **нет** — в REST-документации отсутствует (упомянут лишь в тексте интеграции TTS) | `homeassistant/components/tts/__init__.py` (`TextToSpeechUrlView`, авторизация обязательна): тело `message` (обязателен), `engine_id`, `language`, `options` (`voice`); ответ `{"url", "path"}`, где `path` — `/api/tts_proxy/<token>` (файл отдаётся без авторизации) |

Проверено по ветке `dev` home-assistant/core 2026-10-31. Из-за отсутствия в
документации адаптеры STT/TTS опираются на код HA: изменение внутреннего API HA
может потребовать обновления расширения.

## Ограничения

- Потоковое распознавание (`recognize_stream`) и потоковый синтез (`speech_stream`)
  не поддержаны — REST HA отдаёт ответ целиком.
- Протокол Wyoming не реализован (вариант для будущего — WebSocket `assist_pipeline/run`).
- Файловый кеш TTS с адаптером `ha-tts` не работает: звуковой кеш требует PCM-движок
  (`synth_pcm`), а HA отдаёт готовый файл.
- Режим шлёт фразу без истории диалога эмулятора: контекст беседы ведёт сам HA по
  `conversation_id` (SN колонки).

## Лицензия

MIT — см. [LICENSE](LICENSE).

## Разработка и тесты

```powershell
python -m pytest tests -q
```

Тесты (`ALICA_EMULE_ROOT` — путь к репозиторию эмулятора, по умолчанию рядом) поднимают
локальную заглушку HA (`tests/stub_ha.py`: conversation/process, services, stt,
tts_get_url, tts_proxy с проверкой Bearer) и подключают этот каталог как dev-расширение
к коду эмулятора; реальный Home Assistant не трогается.

Структура: `extension.json` (манифест) · `ha_common.py` (общий HTTP-помощник,
подключается через `importlib.util.spec_from_file_location` относительно `__file__`) ·
`modes/ha.py` · `actions/ha.py` · `scenarios/smart_home/ha.light.json` ·
`voice/adapters/ha-{asr,tts}.py` · `voice/presets/ha-{asr,tts}.json` · `mcp/ha.json` ·
`hooks.py` (пустые точки `on_install/on_enable/on_disable/migrate`) · `tests/`.
