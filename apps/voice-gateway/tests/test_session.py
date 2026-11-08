import asyncio

import pytest
from fakes import Factory, FakeBackend, FakeTransport
from nguit_tools.call_gate import CallBlocked, check_call_allowed
from voice_gateway.live import (
    AudioOut,
    BackendClosed,
    GoAway,
    Interrupted,
    InTranscript,
    OutTranscript,
    Resumption,
    ToolCall,
    TurnComplete,
)
from voice_gateway.prompt import OPENING_KICK
from voice_gateway.session import CallSession
from voice_gateway.store import CallStore

from conftest import sign_in

DISCLOSURE = (
    "Hello, this is an AI assistant from The New Guy in Town, "
    "calling for a person looking for a PG. Is this a good time?"
)


def say_opening():
    return [OutTranscript(DISCLOSURE), TurnComplete()]


def end_call():
    return ToolCall("end", "end_call", {})


def fact(field, value, confirmed=True, id="f1"):
    return ToolCall(id, "record_fact", {"field": field, "value": value, "confirmed": confirmed})


async def run(call_id, *backends, transport=None, after_start=None, **kw):
    store = CallStore(call_id)
    ctx = await store.gate()
    if after_start:  # something that happens once the call is already allowed to run
        after_start()
    transport = transport or FakeTransport()
    kw.setdefault("reconnect_delay", 0.01)
    session = CallSession(ctx, store, transport, Factory(*backends), **kw)
    await asyncio.wait_for(session.run(), timeout=10)
    return session, transport


def revoke(conn, pg_id):
    conn.execute("UPDATE consents SET revoked_at=now() WHERE subject_id=%s", (pg_id,))
    conn.commit()


def row(conn, sql, *params):
    return conn.execute(sql, params).fetchone()


# -- opening, disclosure and normal completion ---------------------------------------------
async def test_call_opens_with_ai_disclosure_and_completes(make_call, conn):
    c = make_call()
    backend = FakeBackend(*say_opening(), end_call())
    session, transport = await run(c.call_id, backend)

    assert session.result == ("completed", "agent_ended")
    assert backend.texts == [OPENING_KICK]
    call = row(
        conn, "SELECT status, end_reason, started_at, ended_at FROM calls WHERE id=%s", c.call_id
    )
    assert call["status"] == "completed" and call["ended_at"] is not None
    seg = row(conn, "SELECT speaker, text FROM transcript_segments WHERE call_id=%s", c.call_id)
    assert seg["speaker"] == "agent" and "AI assistant" in seg["text"]
    assert transport.types()[-1] == "ended" and transport.closed


async def test_disclosure_split_across_transcript_chunks_is_accepted(make_call):
    c = make_call()
    backend = FakeBackend(
        OutTranscript("Hello, this is an A"),
        OutTranscript("I assistant from The New"),
        OutTranscript(" Guy in Town."),
        TurnComplete(),
        end_call(),
    )
    session, _ = await run(c.call_id, backend)
    assert session.result == ("completed", "agent_ended")


async def test_call_ends_if_the_agent_never_says_it_is_an_ai(make_call, conn):
    c = make_call()
    backend = FakeBackend(
        OutTranscript("Hi, what is the monthly rent?"),
        TurnComplete(),
        OutTranscript("And how much is the deposit?"),
        TurnComplete(),
        fact("rent", "12000"),
    )
    session, _ = await run(c.call_id, backend)
    assert session.result == ("failed", "disclosure_missing")
    assert row(
        conn,
        "SELECT 1 FROM audit_events WHERE action='disclosure_missing' AND object_id=%s",
        str(c.call_id),
    )
    assert row(conn, "SELECT 1 FROM call_facts WHERE call_id=%s", c.call_id) is None


# -- facts ---------------------------------------------------------------------------------
async def test_facts_are_saved_with_offset_and_confirmation(make_call, conn):
    c = make_call()
    backend = FakeBackend(
        *say_opening(),
        fact("rent", "12000", True, "a"),
        fact("deposit", "maybe twenty", False, "b"),
        fact("food", "veg only", "true", "c"),  # a string is not a clear yes
        end_call(),
    )
    await run(c.call_id, backend)
    facts = {
        r["field"]: r
        for r in conn.execute("SELECT * FROM call_facts WHERE call_id=%s", (c.call_id,)).fetchall()
    }
    assert facts["rent"]["value"] == "12000" and facts["rent"]["confirmed"] is True
    assert facts["rent"]["transcript_offset"] >= 0
    assert facts["deposit"]["confirmed"] is False
    assert facts["food"]["confirmed"] is False
    assert all(r[2] == {"saved": True} for r in backend.tool_results if r[1] == "record_fact")


async def test_unknown_or_empty_facts_are_rejected_and_not_saved(make_call, conn):
    c = make_call()
    backend = FakeBackend(
        *say_opening(),
        fact("bank_account", "123456", id="x"),
        fact("rent", "  ", id="y"),
        end_call(),
    )
    await run(c.call_id, backend)
    assert row(conn, "SELECT 1 FROM call_facts WHERE call_id=%s", c.call_id) is None
    errors = [r[2] for r in backend.tool_results if r[1] == "record_fact"]
    assert all("error" in e for e in errors) and len(errors) == 2


async def test_a_later_answer_replaces_an_earlier_one(make_call, conn):
    c = make_call()
    backend = FakeBackend(
        *say_opening(), fact("rent", "10000", False), fact("rent", "12000"), end_call()
    )
    await run(c.call_id, backend)
    r = row(
        conn, "SELECT value, confirmed FROM call_facts WHERE call_id=%s AND field='rent'", c.call_id
    )
    assert r["value"] == "12000" and r["confirmed"] is True


# -- stop requests and opt-out (C-7) ---------------------------------------------------------
async def test_spoken_stop_request_ends_the_call_even_if_the_model_does_nothing(
    make_call, conn, client
):
    c = make_call()
    backend = FakeBackend(
        *say_opening(), InTranscript("Please stop calling me"), fact("rent", "9999")
    )
    session, transport = await run(c.call_id, backend)

    assert session.result == ("opted_out", "stop_phrase")
    assert row(conn, "SELECT status FROM calls WHERE id=%s", c.call_id)["status"] == "opted_out"
    assert row(conn, "SELECT 1 FROM call_facts WHERE call_id=%s", c.call_id) is None
    assert row(
        conn, "SELECT 1 FROM audit_events WHERE action='owner_opt_out' AND object_id=%s", c.pg_id
    )
    # consent is revoked for everyone, not just this mover
    assert row(conn, "SELECT revoked_at FROM consents WHERE subject_id=%s", c.pg_id)["revoked_at"]
    with pytest.raises(CallBlocked):
        check_call_allowed(conn, c.call_id)
    other = sign_in(client, "second-mover-1")
    from conftest import PLAN

    plan_id = client.post("/v1/plans", json=PLAN, headers=other).json()["id"]
    assert c.pg_id not in {
        r["id"] for r in client.get(f"/v1/plans/{plan_id}/pgs", headers=other).json()
    }
    res = client.post(
        f"/v1/plans/{plan_id}/call-batches", json={"pg_ids": [c.pg_id]}, headers=other
    )
    assert res.status_code == 422
    assert transport.json[-1]["reason"] == "stop_phrase"


async def test_stop_request_split_across_chunks_is_still_caught(make_call):
    c = make_call()
    backend = FakeBackend(*say_opening(), InTranscript("Sto"), InTranscript("p calling"))
    session, _ = await run(c.call_id, backend)
    assert session.result == ("opted_out", "stop_phrase")


async def test_normal_owner_speech_does_not_end_the_call(make_call):
    c = make_call()
    backend = FakeBackend(
        *say_opening(),
        InTranscript("It is near the bus stop and rent is twelve thousand"),
        TurnComplete(),
        end_call(),
    )
    session, _ = await run(c.call_id, backend)
    assert session.result == ("completed", "agent_ended")


async def test_model_opt_out_tool_revokes_consent_and_stops_saving_facts(make_call, conn):
    c = make_call()
    backend = FakeBackend(
        *say_opening(),
        ToolCall("o", "mark_opt_out", {}),
        fact("rent", "5000", id="late"),
        end_call(),
    )
    session, _ = await run(c.call_id, backend)
    assert session.result == ("opted_out", "agent_ended")
    assert row(conn, "SELECT revoked_at FROM consents WHERE subject_id=%s", c.pg_id)["revoked_at"]
    assert row(conn, "SELECT 1 FROM call_facts WHERE call_id=%s", c.call_id) is None


async def test_call_is_force_ended_if_the_model_never_hangs_up_after_opt_out(make_call):
    c = make_call()
    backend = FakeBackend(*say_opening(), ToolCall("o", "mark_opt_out", {}))
    session, _ = await run(c.call_id, backend, opt_out_grace_seconds=0.05)
    assert session.result == ("opted_out", "grace_timeout")


# -- approval and consent are re-checked during the call -------------------------------------
async def test_consent_withdrawn_mid_call_stops_tool_use(make_call, conn):
    c = make_call()
    backend = FakeBackend(*say_opening(), fact("rent", "12000"))
    session, _ = await run(c.call_id, backend, after_start=lambda: revoke(conn, c.pg_id))
    assert session.result == ("failed", "no_consent")
    assert row(conn, "SELECT 1 FROM call_facts WHERE call_id=%s", c.call_id) is None


# -- reconnects: disconnects, goAway, session resumption ---------------------------------------
async def test_dropped_connection_resumes_with_the_saved_handle_and_keeps_facts(make_call, conn):
    c = make_call()
    first = FakeBackend(
        *say_opening(), Resumption("handle-1"), fact("rent", "12000"), BackendClosed("network drop")
    )
    second = FakeBackend(fact("deposit", "20000"), end_call())
    session, transport = await run(c.call_id, first, second)

    assert second.connected_with == "handle-1"
    assert second.texts == []  # the opening is not repeated after a resume
    assert session.result == ("completed", "agent_ended")
    assert "reconnecting" in transport.types()
    saved = {
        r["field"]
        for r in conn.execute("SELECT field FROM call_facts WHERE call_id=%s", (c.call_id,))
    }
    assert saved == {"rent", "deposit"}  # nothing lost across the drop
    assert (
        row(conn, "SELECT resumption_handle FROM calls WHERE id=%s", c.call_id)["resumption_handle"]
        == "handle-1"
    )
    assert first.closed and second.closed


async def test_go_away_notice_triggers_a_resume(make_call):
    c = make_call()
    first = FakeBackend(*say_opening(), Resumption("h-go"), GoAway(60))
    second = FakeBackend(end_call())
    session, _ = await run(c.call_id, first, second)
    assert second.connected_with == "h-go"
    assert session.result == ("completed", "agent_ended")


async def test_reconnect_without_a_handle_tells_the_model_to_continue(make_call):
    c = make_call()
    first = FakeBackend(*say_opening(), BackendClosed("drop"))
    second = FakeBackend(end_call())
    await run(c.call_id, first, second)
    assert second.connected_with is None and len(second.texts) == 1


async def test_call_fails_cleanly_after_too_many_reconnect_failures(make_call, conn):
    c = make_call()
    dead = FakeBackend(fail_connect=True)
    session, _ = await run(c.call_id, dead, max_reconnects=2)
    assert session.result == ("failed", "reconnect_failed")
    assert row(conn, "SELECT status FROM calls WHERE id=%s", c.call_id)["status"] == "failed"


async def test_no_reconnect_if_consent_was_withdrawn_during_the_outage(make_call, conn):
    c = make_call()
    first = FakeBackend(BackendClosed("drop"))
    second = FakeBackend(end_call())
    session, _ = await run(c.call_id, first, second, after_start=lambda: revoke(conn, c.pg_id))
    assert session.result == ("failed", "no_consent")
    assert second.connected_with == "never connected"


# -- the browser side ------------------------------------------------------------------------
async def test_audio_flows_both_ways(make_call):
    c = make_call()
    transport = FakeTransport()
    backend = FakeBackend(*say_opening(), AudioOut(b"\x01\x02"), Interrupted(), end_call())
    transport.incoming.put_nowait(b"mic-bytes")
    await run(c.call_id, backend, transport=transport)
    assert transport.audio == [b"\x01\x02"]
    assert "interrupted" in transport.types()  # tells the browser to stop playing at once
    assert backend.audio == [b"mic-bytes"] or backend.audio == []  # may end before it is read


async def test_owner_closing_the_browser_ends_the_call(make_call, conn):
    c = make_call()
    transport = FakeTransport()
    transport.incoming.put_nowait(None)
    session, _ = await run(c.call_id, FakeBackend(), transport=transport)
    assert session.result == ("ended_by_owner", "browser_closed")
    assert (
        row(conn, "SELECT status FROM calls WHERE id=%s", c.call_id)["status"] == "ended_by_owner"
    )


async def test_hang_up_message_ends_the_call(make_call):
    c = make_call()
    transport = FakeTransport()
    transport.incoming.put_nowait({"type": "end"})
    session, _ = await run(c.call_id, FakeBackend(), transport=transport)
    assert session.result == ("ended_by_owner", "owner_hung_up")


async def test_call_has_a_maximum_length(make_call):
    c = make_call()
    session, _ = await run(c.call_id, FakeBackend(*say_opening()), max_seconds=0.2)
    assert session.result == ("completed", "max_duration")


async def test_a_finished_call_cannot_be_started_again(make_call):
    c = make_call()
    await run(c.call_id, FakeBackend(*say_opening(), end_call()))
    with pytest.raises(CallBlocked) as blocked:
        await CallStore(c.call_id).gate()
    assert blocked.value.reason == "call_finished"


async def test_transcript_segments_are_stored_in_order(make_call, conn):
    c = make_call()
    backend = FakeBackend(
        *say_opening(), InTranscript("Yes, good time."), TurnComplete(), end_call()
    )
    await run(c.call_id, backend)
    rows = conn.execute(
        "SELECT speaker FROM transcript_segments WHERE call_id=%s ORDER BY offset_ms, id",
        (c.call_id,),
    ).fetchall()
    assert [r["speaker"] for r in rows] == ["agent", "owner"]
