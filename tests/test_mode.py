"""Режим «Home Assistant» (modes/ha.py) на локальной заглушке HA.

Расширение подключено в dev-режиме (tests/conftest.install_extension) — режим
регистрируется как «home-assistant.ha» и отвечает на фразу без сценария вместо
модели (settings.intelligence = "ext:home-assistant.ha"). Проверяются: запрос к
/api/conversation/process (Bearer, text/language/conversation_id), ответ из
response.speech.plain.speech, понятная фраза при недоступности HA и при пустом
адресе, чтение настроек через ctx.extension (правка значений без
рестарта), метаданные MODE (title/tabs/preset) в /emulator/api/intelligence.
"""
import json

from server_emulator.intelligence import extension_modes

from tests.conftest import make_runtime
from tests.stub_ha import SPEECH


async def test_mode_answers_with_ha_speech(tmp_path, stub):
    stub_ha, base = stub
    runtime, ext_id = make_runtime(tmp_path, base)
    try:
        answer = await runtime.chat("включи свет", sn="SN-1")
        assert answer["source"] == "home-assistant.ha"  # режим расширения отвечает
        assert answer["text"] == SPEECH  # текст из response.speech.plain.speech
        assert answer["tool_calls"] == []
        call = stub_ha.calls[-1]
        assert call["kind"] == "conversation" and call["auth"] == "Bearer test-token"
        assert call["body"] == {"text": "включи свет", "language": "ru",
                                "conversation_id": "alice-SN-1"}  # диалог колонки по SN
    finally:
        await runtime.close()


async def test_mode_sends_agent_id_when_set(tmp_path, stub):
    stub_ha, base = stub
    runtime = make_runtime(tmp_path, base)[0]
    runtime.settings["extensions"]["settings"]["home-assistant"]["agent_id"] = \
        "conversation.home_assistant"
    try:
        await runtime.chat("что там", sn="SN-2")
        body = stub_ha.calls[-1]["body"]
        assert body["agent_id"] == "conversation.home_assistant"  # id агента Assist
        assert body["conversation_id"] == "alice-SN-2"
    finally:
        await runtime.close()


async def test_mode_clear_phrase_when_ha_unreachable(tmp_path, stub):
    _, base = stub
    runtime, _ = make_runtime(tmp_path, "http://127.0.0.1:9")  # порт без слушателя
    try:
        answer = await runtime.chat("включи свет")
        assert answer["source"] == "home-assistant.ha"
        assert "недоступен" in answer["text"]  # понятная фраза вместо сбоя режима
    finally:
        await runtime.close()


async def test_mode_clear_phrase_on_http_error(tmp_path, stub):
    stub_ha, base = stub
    runtime, _ = make_runtime(tmp_path, base, token="wrong-token")  # заглушка ответит 401
    try:
        answer = await runtime.chat("включи свет")
        assert answer["source"] == "home-assistant.ha" and "недоступен" in answer["text"]
        assert stub_ha.calls[-1]["auth"] == "Bearer wrong-token"
    finally:
        await runtime.close()


async def test_mode_reports_missing_url(tmp_path, stub):
    runtime = make_runtime(tmp_path, "")[0]  # адрес не задан
    try:
        answer = await runtime.chat("включи свет")
        assert "адрес" in answer["text"] and "Home Assistant" in answer["text"]
    finally:
        await runtime.close()


async def test_mode_reads_settings_via_extension_context(tmp_path, stub):
    """Настройки читаются штатно через ctx.extension: режим ничего не знает
    о Runtime, а правка значений во вкладке «Расширений» видна следующему вызову без
    рестарта — контекст ExtensionContext строится заново на каждый вызов."""
    stub_ha, base = stub
    runtime, _ = make_runtime(tmp_path, base)
    try:
        await runtime.chat("включи свет", sn="SN-1")
        body = stub_ha.calls[-1]["body"]
        assert body["language"] == "ru" and body["conversation_id"] == "alice-SN-1"
        runtime.settings["extensions"]["settings"]["home-assistant"]["language"] = "en"
        await runtime.chat("включи свет", sn="SN-1")
        body = stub_ha.calls[-1]["body"]
        assert body["language"] == "en"  # новое значение — без рестарта сервера
        assert stub_ha.calls[-1]["auth"] == "Bearer test-token"  # токен тоже из настроек
    finally:
        await runtime.close()


async def test_mode_metadata_in_intelligence_api(tmp_path, stub):
    """Метаданные MODE видны перечислению «Интеллекта» (intelligence.extension_modes):
    полный id home-assistant.ha, title/tabs и preset-набор (кнопка «Всё через Home
    Assistant»). HTTP-маршрут /emulator/api/intelligence — passthrough этих
    же данных (ui/api/settings.py), его контрактом занимается эмулятор."""
    _, base = stub
    runtime, _ = make_runtime(tmp_path, base)
    try:
        modes = extension_modes(runtime)
        assert [m["id"] for m in modes] == ["home-assistant.ha"]
        assert modes[0]["title"] == "Home Assistant"
        assert modes[0]["ext"] == "home-assistant"
        assert modes[0]["preset"] == {"asr": "p:home-assistant.ha-asr",
                                      "tts": "p:home-assistant.ha-tts"}
        assert modes[0]["tabs"] == [{"id": "ha", "title": "Диалог"},
                                    {"id": "cfg", "title": "Настройки"}]
    finally:
        await runtime.close()


async def test_mode_json_payload_shape(tmp_path, stub):
    """Тело запроса — ровно контракт /api/conversation/process (text обязателен)."""
    stub_ha, base = stub
    runtime, _ = make_runtime(tmp_path, base)
    try:
        await runtime.chat("привет", history=[{"role": "user", "content": "раньше"}], sn="SN-3")
        body = stub_ha.calls[-1]["body"]
        assert set(body) <= {"text", "language", "conversation_id", "agent_id"}
        assert json.dumps(body, ensure_ascii=False)  # сериализуемо без сюрпризов
    finally:
        await runtime.close()
