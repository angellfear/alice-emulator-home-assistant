"""Действие ha.call_service (actions/ha.py) на локальной заглушке HA.

Проверяются: регистрация в реестре Executor (имя объявлено в permissions.actions —
проверка префикса manager.action_prefix), вызов через JSON-шаг action (правильный
URL /api/services/<domain>/<service>, тело {"entity_id", **data}, Bearer-токен),
слот с ответом HA, ветка on_failure при недоступности HA и прямой вызов функции
действия: настройки — ExtensionContext владельца в execution.extension (его строит manager.action_context), без контекста действие честно отказывается.
"""
from types import SimpleNamespace

from server_emulator.scenario_packages.validate import validate_scenario

from tests.conftest import CTX, make_runtime


def light_scenario():
    return validate_scenario({
        "format_version": 2, "id": "ha.light.test", "version": "1.0.0", "category": "custom",
        "triggers": [{"kind": "phrase", "phrases": ["включи свет"], "match": "contains"}],
        "flow": [
            {"id": "call", "op": "action", "ref": "ha.call_service", "slot": "result",
             "arguments": {"domain": "light", "service": "turn_on", "entity_id": "light.kitchen",
                           "data": {"brightness": 128}},
             "on_failure": "unavailable"},
            {"id": "say", "op": "compose", "reply": {"text": "Готово: {{slots.result.0.state}}"}},
            {"id": "done", "op": "finish"},
            {"id": "unavailable", "op": "compose", "reply": {"text": "HA недоступен."}},
            {"id": "stop", "op": "finish"},
        ]})


async def test_action_registered_via_permissions_declaration(tmp_path, stub):
    _, base = stub
    runtime, _ = make_runtime(tmp_path, base)
    try:
        assert "ha.call_service" in runtime.scenario_executor.actions  # рядом со встроенными
        assert "timer.start" in runtime.scenario_executor.actions
        assert runtime.extensions.warnings == []
    finally:
        await runtime.close()


async def test_action_runs_via_json_step(tmp_path, stub):
    """Полный путь эмулятора: Executor ставит execution.extension —
    действие читает url/token из настроек расширения, не зная Runtime."""
    stub_ha, base = stub
    runtime, _ = make_runtime(tmp_path, base)
    try:
        outcome = await runtime.scenario_executor.execute(light_scenario(), dict(CTX), "dlg-ha")
        assert outcome.status == "finished"
        call = stub_ha.calls[-1]
        assert call["kind"] == "service"
        assert call["path"] == "/api/services/light/turn_on"  # POST {url}/api/services/<domain>/<service>
        assert call["body"] == {"entity_id": "light.kitchen", "brightness": 128}  # entity_id + **data
        assert call["auth"] == "Bearer test-token"
        assert outcome.slots["result"] == [{"entity_id": "light.kitchen", "state": "on"}]
        assert outcome.composed[0][1].Event.AliceResponse.Response.Cards[0].Text == \
            "Готово: on"  # ответ HA доступен шаблону шага compose
    finally:
        await runtime.close()


async def test_action_on_failure_when_ha_down(tmp_path, stub):
    runtime, _ = make_runtime(tmp_path, "http://127.0.0.1:9")
    try:
        outcome = await runtime.scenario_executor.execute(light_scenario(), dict(CTX), "dlg-ha")
        assert outcome.status == "finished"  # on_failure → понятная реплика
        assert outcome.composed[0][1].Event.AliceResponse.Response.Cards[0].Text == "HA недоступен."
    finally:
        await runtime.close()


async def test_action_requires_domain_and_service(tmp_path, stub):
    stub_ha, base = stub
    runtime, _ = make_runtime(tmp_path, base)
    try:
        module = runtime.scenario_executor.actions["ha.call_service"]
        execution = SimpleNamespace(extension=runtime.extensions.action_context("ha.call_service"))
        for arguments in ({"domain": "light"}, {"service": "turn_on"}, {}):
            try:
                await module(dict(arguments), execution)
            except ValueError:
                continue
            raise AssertionError(f"действие приняло {arguments}")
        assert stub_ha.calls == []  # до сети дело не дошло
    finally:
        await runtime.close()


async def test_action_direct_call_reads_extension_context(tmp_path, stub):
    """Прямой вызов (как ctx.action SDK): execution.extension — ExtensionContext
    владельца действия, url/token — из его настроек (сборка контекста —
    manager.action_context, тот же объект, что ставит эмулятор)."""
    stub_ha, base = stub
    runtime, _ = make_runtime(tmp_path, base)
    try:
        module = runtime.scenario_executor.actions["ha.call_service"]
        execution = SimpleNamespace(extension=runtime.extensions.action_context("ha.call_service"))
        assert execution.extension is not None  # владелец найден по permissions.actions
        assert execution.extension.id == "home-assistant"
        result = await module(
            {"domain": "light", "service": "turn_off", "entity_id": "light.kitchen"}, execution)
        assert result == [{"entity_id": "light.kitchen", "state": "on"}]
        call = stub_ha.calls[-1]
        assert call["path"] == "/api/services/light/turn_off"  # url из ExtensionContext
        assert call["auth"] == "Bearer test-token"  # токен из ExtensionContext
    finally:
        await runtime.close()


async def test_action_without_extension_context_refuses(tmp_path, stub):
    """Вызов вне сценария/эмулятора (execution.extension пуст) — RuntimeError, а не
    попытка достать настройки обходом (контракт extensions.md, «Настройки в коде
    расширения»)."""
    stub_ha, base = stub
    runtime, _ = make_runtime(tmp_path, base)
    try:
        module = runtime.scenario_executor.actions["ha.call_service"]
        for execution in (SimpleNamespace(), SimpleNamespace(extension=None), None):
            try:
                await module({"domain": "light", "service": "turn_on"}, execution)
            except RuntimeError as exc:
                assert "настроек" in str(exc)
            else:
                raise AssertionError("действие выполнилось без ExtensionContext")
        assert stub_ha.calls == []
    finally:
        await runtime.close()


async def test_extension_disabled_unregisters_action(tmp_path, stub):
    _, base = stub
    runtime = make_runtime(tmp_path, base)[0]
    try:
        await runtime.extensions.disable("home-assistant")
        assert "ha.call_service" not in runtime.scenario_executor.actions
        await runtime.extensions.enable("home-assistant")
        assert "ha.call_service" in runtime.scenario_executor.actions
    finally:
        await runtime.close()
