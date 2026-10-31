"""Локальная заглушка Home Assistant: aiohttp-сервер на 127.0.0.1 (порт выбирается
системой), ручки — только те, что использует расширение:

  POST /api/conversation/process          — conversation-агент (проверка Bearer)
  POST /api/services/<domain>/<service>   — вызов сервиса (тело и токен — в calls)
  POST /api/stt/<provider>                — STT (проверка X-Speech-Content)
  POST /api/tts_get_url                   — TTS: {"url", "path"} на /api/tts_proxy/<token>
  GET  /api/tts_proxy/<token>             — аудио (без авторизации, как в HA)

Каждый вызов пишется в stub.calls (dict без аудио-байтов — только размер) для
проверок тестов. Реальный Home Assistant по сети тесты не трогают.
"""
from aiohttp import web

SPEECH = "Готово, включаю свет."
STT_TEXT = "включи свет на кухне"
AUDIO = b"ID3\x04fake-ha-audio-bytes"


class StubHA:
    """Заглушка: ручки HA + журнал вызовов."""

    def __init__(self, token="test-token"):
        self.token = token
        self.base = ""  # заполняется в start()
        self.calls = []
        self.tts_relative = False  # True — tts_get_url отвечает только {"path"} (без url)
        self.app = web.Application()
        self.app.router.add_post("/api/conversation/process", self.conversation)
        self.app.router.add_post("/api/services/{domain}/{service}", self.service)
        self.app.router.add_post("/api/stt/{provider}", self.stt)
        self.app.router.add_post("/api/tts_get_url", self.tts_get_url)
        self.app.router.add_get("/api/tts_proxy/{token}", self.tts_proxy)

    def _check_auth(self, request):
        """Bearer-проверка как в HA: Authorization: Bearer <токен долгоживущий>.
        Отказ тоже пишется в calls (kind: denied) — тесты видят попытку."""
        expected = f"Bearer {self.token}" if self.token else None
        given = request.headers.get("Authorization", "")
        if expected is not None and given != expected:
            self.calls.append({"kind": "denied", "path": request.path, "auth": given})
            return web.json_response({"error": "unauthorized"}, status=401)
        return None

    async def conversation(self, request):
        denied = self._check_auth(request)
        if denied is not None:
            return denied
        body = await request.json()
        self.calls.append({"kind": "conversation", "body": body,
                           "auth": request.headers.get("Authorization", "")})
        return web.json_response({
            "response": {"speech": {"plain": {"speech": SPEECH, "extra_data": None}},
                         "card": {}, "language": body.get("language") or "ru",
                         "response_type": "action_done"},
            "conversation_id": body.get("conversation_id") or "cid-1"})

    async def service(self, request):
        denied = self._check_auth(request)
        if denied is not None:
            return denied
        body = await request.json()
        self.calls.append({"kind": "service",
                           "path": request.path,
                           "domain": request.match_info["domain"],
                           "service": request.match_info["service"],
                           "body": body,
                           "auth": request.headers.get("Authorization", "")})
        entity = body.get("entity_id") or "light.kitchen"
        return web.json_response([{"entity_id": entity, "state": "on"}])

    async def stt(self, request):
        denied = self._check_auth(request)
        if denied is not None:
            return denied
        audio = await request.read()
        self.calls.append({"kind": "stt", "provider": request.match_info["provider"],
                           "speech_content": request.headers.get("X-Speech-Content", ""),
                           "audio_bytes": len(audio),
                           "auth": request.headers.get("Authorization", "")})
        return web.json_response({"text": STT_TEXT, "result": "success"})

    async def tts_get_url(self, request):
        denied = self._check_auth(request)
        if denied is not None:
            return denied
        body = await request.json()
        self.calls.append({"kind": "tts_get_url", "body": body,
                           "auth": request.headers.get("Authorization", "")})
        if self.tts_relative:  # вариант ответа: только относительный path
            return web.json_response({"path": "/api/tts_proxy/token-1"})
        return web.json_response({"url": self.base + "/api/tts_proxy/token-1",
                                  "path": "/api/tts_proxy/token-1"})

    async def tts_proxy(self, request):
        self.calls.append({"kind": "tts_proxy", "token": request.match_info["token"]})
        return web.Response(body=AUDIO, content_type="audio/mpeg")


async def start(token="test-token"):
    """Запуск заглушки на свободном порту 127.0.0.1 → (runner, stub, base_url)."""
    stub = StubHA(token=token)
    runner = web.AppRunner(stub.app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    stub.base = f"http://127.0.0.1:{port}"
    return runner, stub, stub.base
