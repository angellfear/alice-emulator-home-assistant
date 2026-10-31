"""Общие помощники тестов расширения Home Assistant.

Тесты исполняются против КОДА ЭМУЛЯТОРА: ALICA_EMULE_ROOT — путь к его каталогу
(по умолчанию репозиторий эмулятора рядом с этим). Расширение подключается в
режиме разработки — запись installed/enabled в settings и load_enabled(), как в
tests/test_extensions_manager.py эмулятора, — файлы берутся из этого репозитория
напрямую. Сеть — только локальная заглушка HA (stub_ha.py), реальный Home
Assistant не трогается.
"""
import datetime
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # корень расширения (extension.json здесь)
EMULATOR = Path(os.environ.get("ALICA_EMULE_ROOT", ROOT.parent / "alica_emule"))  # по умолчанию — рядом
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))  # свой пакет tests важнее одноимённого у эмулятора
if str(EMULATOR) not in sys.path:
    sys.path.insert(1, str(EMULATOR))  # код эмулятора (server_emulator) — следом

import pytest  # noqa: E402

from server_emulator.runtime import Runtime  # noqa: E402

from tests.stub_ha import start as start_stub  # noqa: E402

EXT_ID = json.loads((ROOT / "extension.json").read_text(encoding="utf-8"))["id"]

CTX = {"input": {"text": "", "sn": "SN-1", "request_id": "req-1", "dialog_id": "dlg-ha"},
       "clock": {"now": datetime.datetime(2026, 10, 31, 12, 0)}}


async def ha_stub(token="test-token"):
    """Заглушка HA → (runner, stub, base_url); вызыватель закрывает runner."""
    return await start_stub(token=token)


def install_extension(runtime, values=None, enabled=True):
    """Подключить ЭТОТ репозиторий как dev-расширение (без копирования) и сохранить
    значения настроек; load_enabled() подхватывает modes/actions/scenarios/…"""
    state = runtime.settings.setdefault("extensions", {})
    state.setdefault("installed", {})[EXT_ID] = {"version": "1.0.0", "dev": str(ROOT)}
    state.setdefault("enabled", {})[EXT_ID] = enabled
    if values is not None:
        state.setdefault("settings", {})[EXT_ID] = dict(values)
    runtime.extensions.load_enabled()
    return EXT_ID


def make_runtime(tmp_path, stub_url, token="test-token", enabled=True, level="ext:home-assistant.ha"):
    """Runtime с подключённым расширением, настройками на заглушку HA и режимом
    «Интеллекта» ext:home-assistant.ha (как его ставит вкладка «Интеллект»)."""
    runtime = Runtime(tmp_path)
    install_extension(runtime, values={"url": stub_url, "token": token}, enabled=enabled)
    if level:
        runtime.settings["intelligence"] = level
    return runtime, EXT_ID


@pytest.fixture
async def stub():
    """Заглушка HA на время теста: (stub, base_url); сервер закрывается сам."""
    runner, stub_ha, base = await start_stub()
    try:
        yield stub_ha, base
    finally:
        await runner.cleanup()
