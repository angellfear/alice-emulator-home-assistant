"""Адаптеры ASR/TTS (voice/adapters/) на локальной заглушке HA.

Адаптеры грузятся напрямую из файлов расширения (importlib — как их грузит
voice_stack), runtime — двойник с общим клиентом Lifecycle (тот же интерфейс,
что у адаптера openai в эмуляторе). Проверяются: transcribe → POST /api/stt
(X-Speech-Content из RIFF-заголовка WAV, Bearer-токен, текст из {"text"}),
speech → POST /api/tts_get_url + GET /api/tts_proxy (message из payload["input"],
байты и content_type), env:ИМЯ в токене пресета, токен из настроек расширения
(аргумент extension, приоритет у api_key пресета), понятные ошибки.
"""
import importlib.util
import io
import os
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import ClientSession

from server_emulator.sdk import ExtensionContext

from tests.stub_ha import AUDIO, STT_TEXT

ROOT = Path(__file__).resolve().parents[1]


class FakeLifecycle:
    """Минимальный Lifecycle: один общий клиент (как в эмуляторе)."""

    def __init__(self, session):
        self._session = session

    def client_session(self):
        return self._session


@pytest.fixture
async def runtime_with_session():
    async with ClientSession() as session:
        yield SimpleNamespace(lifecycle=FakeLifecycle(session))


def load_adapter(name):
    spec = importlib.util.spec_from_file_location(f"voice_adapter_{name}", ROOT / "voice" / "adapters" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def wav_bytes(rate=16000, bits=2, channels=1):
    """Минимальный WAV (PCM) с корректным RIFF-заголовком — как шлёт конвейер эмулятора."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(bits)
        handle.setframerate(rate)
        handle.writeframes(b"\0" * (rate * bits * channels // 10))  # 100 мс тишины
    return buffer.getvalue()


# --- ASR: /api/stt/<provider> -------------------------------------------------------

async def test_asr_transcribes_wav(tmp_path, stub, runtime_with_session):
    stub_ha, base = stub
    adapter = load_adapter("ha-asr")
    text = await adapter.transcribe(runtime_with_session,
                                    {"url": base + "/api/stt/stt.piper", "api_key": "test-token",
                                     "language": "ru_ru"},
                                    wav_bytes(), "input.wav")
    assert text == STT_TEXT  # текст из {"text", "result"} заглушки
    call = stub_ha.calls[-1]
    assert call["kind"] == "stt" and call["provider"] == "stt.piper"
    assert call["audio_bytes"] > 0
    # метаданные — из RIFF-заголовка: формат/кодек/частота/биты/каналы/язык
    assert call["speech_content"] == ("format=wav; codec=pcm; sample_rate=16000; "
                                      "bit_rate=16; channel=1; language=ru_ru")


async def test_asr_reads_sample_rate_from_wav_header(tmp_path, runtime_with_session):
    from tests.stub_ha import start
    runner, stub_ha, base = await start(token=None)  # без токена: проверяем только метаданные
    try:
        adapter = load_adapter("ha-asr")
        await adapter.transcribe(runtime_with_session,
                                 {"url": base + "/api/stt/stt.piper", "api_key": "", "language": "ru_ru"},
                                 wav_bytes(rate=48000, bits=4, channels=2), "mic.wav")
        header = stub_ha.calls[-1]["speech_content"]
        assert "sample_rate=48000" in header and "bit_rate=32" in header and "channel=2" in header
    finally:
        await runner.cleanup()


async def test_asr_token_from_env(tmp_path, stub, runtime_with_session, monkeypatch):
    stub_ha, base = stub
    monkeypatch.setenv("HA_TEST_TOKEN", "test-token")  # значение заглушки
    adapter = load_adapter("ha-asr")
    await adapter.transcribe(runtime_with_session,
                             {"url": base + "/api/stt/stt.piper", "api_key": "env:HA_TEST_TOKEN"},
                             wav_bytes(), "input.wav")
    assert stub_ha.calls[-1]["auth"] == "Bearer test-token"  # env:ИМЯ раскрыт, не отправлен


async def test_asr_token_falls_back_to_extension_settings(tmp_path, stub, runtime_with_session):
    """extension=: пустой api_key пресета дополняется токеном из настроек
    расширения — ExtensionContext, как его строит эмулятор (env:ИМЯ уже раскрыт)."""
    stub_ha, base = stub
    adapter = load_adapter("ha-asr")
    extension = ExtensionContext("home-assistant", {"url": base, "token": "test-token"})
    await adapter.transcribe(runtime_with_session,
                             {"url": base + "/api/stt/stt.piper", "api_key": "", "language": "ru_ru"},
                             wav_bytes(), "input.wav", extension=extension)
    assert stub_ha.calls[-1]["auth"] == "Bearer test-token"


async def test_asr_preset_api_key_wins_over_extension(tmp_path, stub, runtime_with_session):
    """Приоритет: api_key пресета сильнее токена настроек расширения (когда задан)."""
    stub_ha, base = stub
    adapter = load_adapter("ha-asr")
    extension = ExtensionContext("home-assistant", {"url": base, "token": "test-token"})
    with pytest.raises(ValueError, match="401"):  # заглушка отклонит неверный токен
        await adapter.transcribe(runtime_with_session,
                                 {"url": base + "/api/stt/stt.piper", "api_key": "wrong"},
                                 wav_bytes(), "input.wav", extension=extension)
    assert stub_ha.calls[-1]["kind"] == "denied" and stub_ha.calls[-1]["auth"] == "Bearer wrong"


async def test_asr_bad_token_is_clear_error(tmp_path, stub, runtime_with_session):
    stub_ha, base = stub
    adapter = load_adapter("ha-asr")
    with pytest.raises(ValueError, match="401"):
        await adapter.transcribe(runtime_with_session,
                                 {"url": base + "/api/stt/stt.piper", "api_key": "wrong"},
                                 wav_bytes(), "input.wav")


# --- TTS: /api/tts_get_url + /api/tts_proxy ------------------------------------------

async def test_tts_speaches_via_get_url(tmp_path, stub, runtime_with_session):
    stub_ha, base = stub
    adapter = load_adapter("ha-tts")
    audio, content_type = await adapter.speech(runtime_with_session,
                                               {"url": base + "/api/tts_get_url",
                                                "api_key": "test-token", "engine_id": "tts.piper",
                                                "language": "ru", "voice": "irina"},
                                               {"input": "Привет!", "model": "", "voice": "",
                                                "response_format": "mp3"})
    assert audio == AUDIO and content_type == "audio/mpeg"  # байты из tts_proxy
    call = stub_ha.calls[-2]
    assert call["kind"] == "tts_get_url" and call["auth"] == "Bearer test-token"
    assert call["body"] == {"message": "Привет!", "engine_id": "tts.piper",  # message из payload["input"]
                            "language": "ru", "options": {"voice": "irina"}}
    assert stub_ha.calls[-1]["kind"] == "tts_proxy"  # файл получен по url из ответа


async def test_tts_relative_path_resolved(tmp_path, stub):
    """Если HA вернул только path — он разворачивается от базы tts_get_url."""
    stub_ha, base = stub
    stub_ha.tts_relative = True
    async with ClientSession() as session:
        runtime = SimpleNamespace(lifecycle=FakeLifecycle(session))
        adapter = load_adapter("ha-tts")
        audio, _ = await adapter.speech(runtime, {"url": base + "/api/tts_get_url",
                                                  "api_key": "test-token"}, {"input": "Текст"})
    assert audio == AUDIO
    assert stub_ha.calls[-1]["kind"] == "tts_proxy"  # path развёрнут до абсолютного url


async def test_tts_empty_text_rejected(tmp_path, stub, runtime_with_session):
    _, base = stub
    adapter = load_adapter("ha-tts")
    with pytest.raises(ValueError, match="пустой"):
        await adapter.speech(runtime_with_session, {"url": base + "/api/tts_get_url"}, {})


async def test_tts_token_falls_back_to_extension_settings(tmp_path, stub, runtime_with_session):
    """extension= у TTS: пустой api_key пресета дополняется токеном
    настроек расширения (ExtensionContext), заголовок уходит с Bearer."""
    stub_ha, base = stub
    adapter = load_adapter("ha-tts")
    extension = ExtensionContext("home-assistant", {"url": base, "token": "test-token"})
    audio, content_type = await adapter.speech(
        runtime_with_session,
        {"url": base + "/api/tts_get_url", "api_key": "", "engine_id": "tts.piper", "language": "ru"},
        {"input": "Привет!"}, extension=extension)
    assert audio == AUDIO and content_type == "audio/mpeg"
    assert stub_ha.calls[-2]["kind"] == "tts_get_url" and stub_ha.calls[-2]["auth"] == "Bearer test-token"


async def test_adapters_declare_services_and_match():
    asr, tts = load_adapter("ha-asr"), load_adapter("ha-tts")
    assert set(asr.SERVICES) == {"asr"} and set(tts.SERVICES) == {"tts"}
    assert asr.MATCH["asr"] and tts.MATCH["tts"]
    assert hasattr(asr, "transcribe") and hasattr(tts, "speech")
    assert tts.streams({}) is False  # потокового синтеза нет (REST отдаёт файл целиком)
