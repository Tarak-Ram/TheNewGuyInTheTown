import json
import os
from uuid import UUID

from fastapi import WebSocket
from nguit_tools import call_token
from nguit_tools.call_gate import CallBlocked, CallContext
from nguit_tools.health import create_app
from starlette.websockets import WebSocketDisconnect, WebSocketState

from voice_gateway.live import GeminiLiveBackend, LiveBackend
from voice_gateway.postcall import extract_after_call
from voice_gateway.session import CallSession
from voice_gateway.stop_classifier import get_stop_classifier
from voice_gateway.store import CallStore

app = create_app("voice-gateway", "Voice Gateway")


def default_backend_factory(ctx: CallContext) -> LiveBackend:
    return GeminiLiveBackend(language=ctx.language)


app.state.backend_factory = default_backend_factory


class WsTransport:
    """Adapts a browser WebSocket: binary frames are audio, text frames are JSON control."""

    def __init__(self, ws: WebSocket):
        self.ws = ws

    async def recv(self) -> bytes | dict | None:
        try:
            msg = await self.ws.receive()
        except (WebSocketDisconnect, RuntimeError):
            return None
        if msg["type"] == "websocket.disconnect":
            return None
        if msg.get("bytes") is not None:
            return msg["bytes"]
        try:
            data = json.loads(msg.get("text") or "{}")
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    async def send_audio(self, data: bytes) -> None:
        if self.ws.client_state == WebSocketState.CONNECTED:
            await self.ws.send_bytes(data)

    async def send_json(self, data: dict) -> None:
        if self.ws.client_state == WebSocketState.CONNECTED:
            await self.ws.send_text(json.dumps(data))

    async def close(self) -> None:
        if self.ws.client_state == WebSocketState.CONNECTED:
            await self.ws.close()


def _allowed_origins() -> set[str]:
    raw = os.environ.get("WEB_ORIGINS", "http://localhost:3000")
    return {o.strip() for o in raw.split(",") if o.strip()}


async def _reject(ws: WebSocket, reason: str) -> None:
    await ws.send_text(json.dumps({"type": "ended", "status": "rejected", "reason": reason}))
    await ws.close(code=4403)


@app.websocket("/v1/calls/{call_id}/web")
async def web_call(ws: WebSocket, call_id: UUID, token: str = "") -> None:
    await ws.accept()
    origin = ws.headers.get("origin")
    if origin and origin not in _allowed_origins():
        return await _reject(ws, "origin_not_allowed")
    try:
        jti = call_token.verify(token, call_id)
    except call_token.TokenError:
        return await _reject(ws, "invalid_token")

    store = CallStore(call_id)
    try:
        ctx = await store.gate()  # approval, consent, opt-out, switch: checked again here
    except CallBlocked as blocked:
        return await _reject(ws, blocked.reason)
    if not await store.claim_token(call_token.hash_jti(jti)):
        return await _reject(ws, "token_already_used")

    session = CallSession(
        ctx,
        store,
        WsTransport(ws),
        ws.app.state.backend_factory,
        stop_classifier=get_stop_classifier(),  # None without a model: patterns only
    )
    await session.run()
    await extract_after_call(call_id)  # the browser is already disconnected at this point
