"""Check actual model access without printing credentials or provider error bodies."""
import json
import argparse
import asyncio

import httpx

from .config import get_settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--realtime", action="store_true")
    args = parser.parse_args()
    if args.realtime:
        asyncio.run(probe_realtime())
        return
    key = get_settings().ai_key().get_secret_value()
    if not key:
        print(json.dumps({"keyConfigured": False, "status": "AI_NOT_CONFIGURED"}))
        raise SystemExit(1)
    try:
        response = httpx.get("https://api.openai.com/v1/models/gpt-live-transcribe", headers={"Authorization": "Bearer " + key}, timeout=15)
        print(json.dumps({"keyConfigured": True, "model": "gpt-live-transcribe", "httpStatus": response.status_code, "accessible": response.status_code == 200}))
    except Exception as error:
        print(json.dumps({"keyConfigured": True, "status": "PROVIDER_UNREACHABLE", "errorType": type(error).__name__}))
        raise SystemExit(1)


async def probe_realtime():
    from .realtime_provider import transcription_connection, ProviderError
    try:
        async with transcription_connection("diagnostic-user") as (socket, provider_session):
            print(json.dumps({"realtimeConfigured": True, "providerSessionCreated": bool(provider_session), "model": get_settings().stt_model}))
    except ProviderError as error:
        print(json.dumps({"realtimeConfigured": False, "code": error.code}))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
