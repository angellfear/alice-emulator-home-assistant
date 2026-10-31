"""Общий помощник кода расширения Home Assistant (режим, действие, адаптеры) —
только сеть и заголовки. Настройки код расширения читает штатно через
ExtensionContext (docs/contracts/extensions.md «Настройки в коде
расширения»): режим — ctx.extension, действие — execution.extension, адаптер —
аргумент extension= (если конвейер его передаёт). Доступа к внутренностям
эмулятора здесь нет: Runtime, менеджер настроек и раскрытие `env:ИМЯ` — забота
ExtensionContext (строки вида `env:ИМЯ` в настройках расширения уже раскрыты);
токен пресетов адаптеры раскрывают публичным server_emulator.sdk.secret (SDK 1.2.0,
контракт extensions.md «Настройки в коде расширения»). Подключение — по рецепту
контракта: importlib.util.spec_from_file_location относительно __file__ (файлы
расширения лежат в подкаталогах рядом, пути не зависят от того, откуда оно
запущено).
"""
from __future__ import annotations

from server_emulator.sdk import secret

EXT_ID = "home-assistant"
TIMEOUT_S = 10.0  # таймаут одного запроса к HA


def auth_headers(value):
    """Заголовок Authorization Bearer по значению поля (token/api_key); пусто — без него.
    Значениям настроек расширения раскрытие уже сделано ExtensionContext'ом, повторный
    вызов безвреден; токен пресета адаптеры раскрывают этим же помощником."""
    token = str(secret(value) or "").strip()
    return {"Authorization": "Bearer " + token} if token else {}


def shared_session(runtime):
    """Общий aiohttp-клиент эмулятора (runtime.lifecycle.client_session() — публичный
    контракт voice-stack.md) или None — тогда вызывающий ходит своим клиентом."""
    session = getattr(getattr(runtime, "lifecycle", None), "client_session", None)
    try:
        return session() if callable(session) else None
    except Exception:  # noqa: BLE001 — закрытый Lifecycle не должен ронять вызов
        return None


async def post_json(url, payload, token, timeout=TIMEOUT_S, session=None):
    """POST JSON в HA с Bearer-токеном; ответ — (status, разобранный JSON).
    Транспортная ошибка (сеть, таймаут, не-JSON) — исключение; HTTP-код — статус.

    session — общий клиент эмулятора, если вызывающий его имеет (адаптеры голосового
    стека). Режим и действие своего клиента не получают (SDK не отдаёт Runtime) —
    создаётся одноразовая aiohttp-сессия на вызов; HA в домашней сети, накладные
    расходы несущественны.
    """
    import aiohttp
    own = None
    if session is None:
        own = session = aiohttp.ClientSession()
    try:
        async with session.post(url, json=payload, headers=auth_headers(token),
                                timeout=aiohttp.ClientTimeout(total=timeout)) as response:
            try:
                data = await response.json(content_type=None)
            except (ValueError, aiohttp.ContentTypeError):
                data = None
            return response.status, data
    finally:
        if own is not None:
            await own.close()
