"""Манифест расширения: валидация extension.json по схеме эмулятора
(server_emulator/extensions/schema.json).

jsonschema в зависимостях эмулятора нет (docs/contracts/extensions.md) — сначала
пробуем проверить документ схемой через jsonschema; при его отсутствии сверяем
структуру валидатором менеджера расширений (validate_manifest — ручная проверка по
той же схеме, включая запрет неизвестных полей). Дополнительно — целостность
вкладов: пресеты ссылаются на адаптеры расширения, id пресета равен имени файла,
MODE объявляет набор «Всё через Home Assistant».
"""
import ast
import json

from tests.conftest import EMULATOR, ROOT

MANIFEST = json.loads((ROOT / "extension.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((EMULATOR / "server_emulator" / "extensions" / "schema.json")
                    .read_text(encoding="utf-8"))


def validate_by_schema(data):
    """jsonschema, если установлен; иначе — валидатор менеджера (та же схема)."""
    try:
        import jsonschema
    except ImportError:
        from server_emulator.extensions.manager import validate_manifest
        return validate_manifest(data)  # ручная проверка по той же структуре
    jsonschema.validate(data, SCHEMA)
    return data


def test_manifest_is_valid():
    assert validate_by_schema(MANIFEST) is not None


def test_manifest_identity_and_permissions():
    assert MANIFEST["id"] == "home-assistant"
    assert "ha.call_service" in MANIFEST["permissions"]["actions"]  # имя вне префикса id
    assert MANIFEST["permissions"]["device_push"] is False
    assert MANIFEST["permissions"]["install"] is False
    hosts = MANIFEST["permissions"]["network"]
    assert "localhost" in hosts and "127.0.0.1" in hosts and "homeassistant.local" in hosts


def test_settings_fields_and_defaults():
    fields = {field["key"] for field in MANIFEST["settings"]["fields"]}
    assert {"url", "token", "agent_id", "language"} <= fields
    defaults = MANIFEST["settings"]["defaults"]
    assert defaults["language"] == "ru" and defaults["token"] == ""
    assert defaults["url"].startswith("http")


def test_voice_presets_reference_extension_adapters():
    adapters = sorted(p.stem for p in (ROOT / "voice" / "adapters").glob("*.py"))
    assert adapters == ["ha-asr", "ha-tts"]
    for preset_path in sorted((ROOT / "voice" / "presets").glob("*.json")):
        preset = json.loads(preset_path.read_text(encoding="utf-8"))
        assert preset["id"] == preset_path.stem  # id пресета = имени файла (voice_stack)
        assert preset["adapter"] == f"home-assistant.{preset_path.stem}"
        assert preset["service"] == preset_path.stem.split("-")[1]
        assert set(preset["values"]) >= {"url", "api_key"}


def test_mode_declares_preset_bundle():
    """MODE режима: id/title/tabs и preset-набор «Всё через Home Assistant»
    (кнопка одного клика: пресеты ASR/TTS + режим, ui/extensions.js applyPreset)."""
    tree = ast.parse((ROOT / "modes" / "ha.py").read_text(encoding="utf-8"))
    mode = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "MODE" for target in node.targets):
            mode = ast.literal_eval(node.value)
    assert isinstance(mode, dict) and mode["id"] == "ha"
    assert mode["title"] == "Home Assistant"
    assert mode["tabs"] and mode["needs"] == ["network"]
    assert mode["preset"] == {"asr": "p:home-assistant.ha-asr", "tts": "p:home-assistant.ha-tts"}


def test_mcp_description_matches_emulator_rules():
    """mcp/ha.json — форма mcp.json эмулятора (mcp_hub.validate_config):
    имя получит префикс расширения → id сервера home-assistant.ha."""
    from server_emulator.mcp_hub import validate_config
    data = json.loads((ROOT / "mcp" / "ha.json").read_text(encoding="utf-8"))
    assert validate_config(data)["mcpServers"]["ha"]["type"] == "http"
    assert data["mcpServers"]["ha"]["disabled"] is True  # до вписывания токена выключен
    assert "Authorization" in data["mcpServers"]["ha"]["headers"]


def test_scenario_matches_emulator_validator():
    """Сценарий-пример проходит validate_scenario эмулятора (формат JSON v2)."""
    from server_emulator.scenario_packages.validate import validate_scenario
    data = json.loads((ROOT / "scenarios" / "smart_home" / "ha.light.json")
                      .read_text(encoding="utf-8"))
    assert validate_scenario(data)["id"] == "ha.light"


def test_requires_sdk_covers_extension_context():
    """Код расширения читает настройки через ExtensionContext — тип
    появился в SDK 1.2.0, нижняя граница требования это закрепляет."""
    from server_emulator.sdk import SDK_VERSION
    floor = MANIFEST["requires"]["sdk"]
    assert "1.2.0" in floor
    assert floor.index("1.2.0") < floor.index("<")  # >=1.2.0 … <2.0.0
    assert SDK_VERSION.startswith("1.")  # текущий SDK внутри объявленного диапазона
