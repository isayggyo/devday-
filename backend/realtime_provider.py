"""Official transcription-only Realtime API; credentials remain inside the backend."""
from contextlib import asynccontextmanager
import asyncio
import hashlib
import json

from websockets.asyncio.client import connect
from .config import get_settings

URL = "wss://api.openai.com/v1/realtime?intent=transcription"


class ProviderError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def configuration():
    settings = get_settings()
    return {"type": "session.update", "session": {"type": "transcription", "audio": {"input": {
        "format": {"type": "audio/pcm", "rate": 24000},
        "transcription": {"model": settings.stt_model, "delay": settings.stt_delay, "languages": ["ko", "en"]},
        "turn_detection": None,
    }}}}


@asynccontextmanager
async def transcription_connection(user_id):
    key = get_settings().ai_key().get_secret_value()
    if not key:
        raise ProviderError("AI_NOT_CONFIGURED")
    try:
        async with connect(URL, additional_headers={"Authorization": "Bearer " + key, "OpenAI-Safety-Identifier": hashlib.sha256(user_id.encode()).hexdigest()}, open_timeout=15, close_timeout=3, max_size=2 * 1024 * 1024) as socket:
            initial = json.loads(await asyncio.wait_for(socket.recv(), 15))
            if initial.get("type") != "session.created":
                raise ProviderError("STT_SESSION_REJECTED")
            await socket.send(json.dumps(configuration()))
            while True:
                event = json.loads(await asyncio.wait_for(socket.recv(), 15))
                if event.get("type") == "error":
                    raise ProviderError("STT_CONFIGURATION_REJECTED")
                if event.get("type") == "session.updated":
                    yield socket, initial.get("session", {}).get("id")
                    break
    except ProviderError:
        raise
    except Exception as error:
        status = getattr(getattr(error, "response", None), "status_code", None)
        code = "AI_AUTH_FAILED" if status in {401, 403} else "AI_RATE_LIMIT" if status == 429 else "STT_CONNECTION_FAILED"
        raise ProviderError(code) from None
