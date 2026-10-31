"""Сценарий-пример «включи свет на кухне» (scenarios/smart_home/ha.light.json).

Проверяются: template-триггер hassil («включи свет на кухне», перестановка
«свет включи на кухне», «потуши свет в спальне») с разбором сущностей в slots
(список room — встроенный lexicons.json эмулятора, power — свой), чужие фразы не
совпадают, полный прогон через Executor эмулятора: действие ha.call_service доходит
до заглушки HA с entity_id из таблицы room_entity, on_failure даёт понятную реплику.
"""
import json

from server_emulator.scenario_engine.templates import TemplateIndex
from server_emulator.scenario_packages.validate import validate_scenario

from tests.conftest import CTX, ROOT, make_runtime


def load_scenario():
    return json.loads((ROOT / "scenarios" / "smart_home" / "ha.light.json").read_text(encoding="utf-8"))


async def test_template_trigger_matches_phrases():
    scenario = load_scenario()
    index = TemplateIndex([scenario])  # списки: свои триггера + встроенные (room)
    for text, power, room in (("включи свет на кухне", "turn_on", "кухня"),
                              ("свет включи на кухне", "turn_on", "кухня"),  # перестановка (a; б)
                              ("потуши свет в спальне", "turn_off", "спальня"),
                              ("зажги свет в гостиной", "turn_on", "гостиная")):
        found = index.match(text)
        assert found is not None, text
        scenario_id, slots = found
        assert scenario_id == "ha.light"
        assert slots.get("power") == power and slots.get("room") == room, (text, slots)


async def test_template_does_not_match_foreign_phrases():
    index = TemplateIndex([load_scenario()])
    for text in ("включи телевизор на кухне", "какая погода", "включи свет"):
        assert index.match(text) is None, text  # комната обязательна: без неё — мимо


async def test_scenario_end_to_end_through_executor(tmp_path, stub):
    stub_ha, base = stub
    runtime, _ = make_runtime(tmp_path, base)
    try:
        scenario = validate_scenario(load_scenario())
        ctx = dict(CTX)
        ctx["input"] = dict(CTX["input"], text="включи свет на кухне")
        ctx["slots"] = {"power": "turn_on", "room": "кухня"}  # слоты даёт template-триггер
        outcome = await runtime.scenario_executor.execute(scenario, ctx, "dlg-ha-light")
        assert outcome.status == "finished"
        call = stub_ha.calls[-1]
        assert call["path"] == "/api/services/light/turn_on"  # действие ha.call_service
        assert call["body"] == {"entity_id": "light.kitchen"}  # entity_id из таблицы room_entity
        assert outcome.composed[0][1].Event.AliceResponse.Response.Cards[0].Text == \
            "Свет (кухня) включён."
    finally:
        await runtime.close()


async def test_scenario_failure_reply_when_ha_down(tmp_path, stub):
    runtime, _ = make_runtime(tmp_path, "http://127.0.0.1:9")
    try:
        scenario = validate_scenario(load_scenario())
        ctx = dict(CTX)
        ctx["input"] = dict(CTX["input"], text="выключи свет на кухне")
        ctx["slots"] = {"power": "turn_off", "room": "кухня"}
        outcome = await runtime.scenario_executor.execute(scenario, ctx, "dlg-ha-light-down")
        assert outcome.status == "finished"  # on_failure → понятная реплика
        assert "недоступен" in outcome.composed[0][1].Event.AliceResponse.Response.Cards[0].Text
    finally:
        await runtime.close()
