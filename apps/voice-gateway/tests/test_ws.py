import json
from uuid import uuid4

import pytest
from fakes import Factory, FakeBackend
from fastapi.testclient import TestClient
from nguit_tools import call_token
from starlette.websockets import WebSocketDisconnect
from voice_gateway.live import OutTranscript, ToolCall, TurnComplete
from voice_gateway.main import app as gateway_app
from voice_gateway.store import CallStore

OPENING = "This is an AI assistant from The New Guy in Town, calling for someone looking for a PG."


@pytest.fixture
def gw(client):  # `client` sets DATABASE_URL for this test
    def use(*backends):
        gateway_app.state.backend_factory = Factory(*backends)
        return TestClient(gateway_app)

    yield use


def good_backend():
    return FakeBackend(OutTranscript(OPENING), TurnComplete(), ToolCall("e", "end_call", {}))


def first_message(ws):
    return json.loads(ws.receive_text())


def final_message(ws):
    last = None
    while True:
        try:
            msg = ws.receive()
        except WebSocketDisconnect:
            return last
        if msg["type"] == "websocket.close":
            return last
        if msg.get("text"):
            last = json.loads(msg["text"])


def session_token(client, c):
    return client.post(f"/v1/calls/{c.call_id}/web-session", headers=c.headers).json()["token"]


def test_valid_token_runs_the_call_to_the_end(client, gw, make_call):
    c = make_call()
    token = session_token(client, c)
    with gw(good_backend()).websocket_connect(f"/v1/calls/{c.call_id}/web?token={token}") as ws:
        assert first_message(ws) == {"type": "state", "state": "connected"}
        end = final_message(ws)
    assert end["type"] == "ended" and end["status"] == "completed"


def test_garbage_token_is_rejected(client, gw, make_call):
    c = make_call()
    with gw(good_backend()).websocket_connect(f"/v1/calls/{c.call_id}/web?token=nope") as ws:
        assert first_message(ws)["reason"] == "invalid_token"


def test_missing_token_is_rejected(client, gw, make_call):
    c = make_call()
    with gw(good_backend()).websocket_connect(f"/v1/calls/{c.call_id}/web") as ws:
        assert first_message(ws)["reason"] == "invalid_token"


def test_token_for_another_call_is_rejected(client, gw, make_call):
    a, b = make_call(), make_call()
    token = session_token(client, a)
    with gw(good_backend()).websocket_connect(f"/v1/calls/{b.call_id}/web?token={token}") as ws:
        assert first_message(ws)["reason"] == "invalid_token"


def test_unapproved_call_cannot_connect_even_with_a_valid_token(client, gw, make_call, conn):
    c = make_call(approve=False)
    call_id = conn.execute("SELECT id FROM calls WHERE batch_id=%s", (c.batch_id,)).fetchone()["id"]
    token, _ = call_token.mint(call_id)  # a token minted without the API's checks
    with gw(good_backend()).websocket_connect(f"/v1/calls/{call_id}/web?token={token}") as ws:
        assert first_message(ws)["reason"] == "not_approved"


def test_opted_out_pg_cannot_be_connected(client, gw, make_call, conn):
    c = make_call()
    token = session_token(client, c)
    conn.execute("UPDATE consents SET revoked_at=now() WHERE subject_id=%s", (c.pg_id,))
    conn.commit()
    with gw(good_backend()).websocket_connect(f"/v1/calls/{c.call_id}/web?token={token}") as ws:
        assert first_message(ws)["reason"] == "no_consent"


def test_other_websites_cannot_open_the_gateway(client, gw, make_call):
    c = make_call()
    token = session_token(client, c)
    url = f"/v1/calls/{c.call_id}/web?token={token}"
    with gw(good_backend()).websocket_connect(url, headers={"origin": "http://evil.example"}) as ws:
        assert first_message(ws)["reason"] == "origin_not_allowed"


def test_the_web_app_origin_is_allowed(client, gw, make_call):
    c = make_call()
    token = session_token(client, c)
    url = f"/v1/calls/{c.call_id}/web?token={token}"
    with gw(good_backend()).websocket_connect(
        url, headers={"origin": "http://localhost:3000"}
    ) as ws:
        assert first_message(ws)["type"] == "state"


def test_a_call_link_works_only_once(client, gw, make_call):
    c = make_call()
    token = session_token(client, c)
    url = f"/v1/calls/{c.call_id}/web?token={token}"
    http = gw(good_backend())
    with http.websocket_connect(url) as ws:
        final_message(ws)
    with http.websocket_connect(url) as ws:
        assert first_message(ws)["reason"] == "call_finished"


async def test_token_claim_is_atomic_and_single_use(client, make_call):
    c = make_call()
    token = session_token(client, c)
    jti = call_token.verify(token, c.call_id)
    store = CallStore(c.call_id)
    assert await store.claim_token(call_token.hash_jti(jti)) is True
    assert await store.claim_token(call_token.hash_jti(jti)) is False


async def test_wrong_token_hash_cannot_claim(client, make_call):
    c = make_call()
    session_token(client, c)
    assert await CallStore(c.call_id).claim_token(call_token.hash_jti("guess")) is False


def test_unknown_call_is_rejected(client, gw):
    call_id = uuid4()
    token, _ = call_token.mint(call_id)
    with gw(good_backend()).websocket_connect(f"/v1/calls/{call_id}/web?token={token}") as ws:
        assert first_message(ws)["reason"] == "not_found"
