from uuid import uuid4

import psycopg
import pytest
from nguit_tools import call_token
from nguit_tools.call_gate import CallBlocked, check_call_allowed

from conftest import PLAN, sign_in


def plan_for(client, name):
    h = sign_in(client, name)
    return h, client.post("/v1/plans", json=PLAN, headers=h).json()["id"]


def revoke(conn, pg_id):
    conn.execute(
        "UPDATE consents SET revoked_at = now() WHERE subject_id = %s AND revoked_at IS NULL",
        (pg_id,),
    )
    conn.commit()


def test_only_consented_pgs_are_listed_and_no_phone_numbers(client, conn, new_pg):
    pg_id = new_pg()
    h, plan_id = plan_for(client, "listing-user-1")
    rows = client.get(f"/v1/plans/{plan_id}/pgs", headers=h).json()
    assert pg_id in {r["id"] for r in rows}
    assert "phone" not in str(rows).lower()
    revoke(conn, pg_id)
    rows = client.get(f"/v1/plans/{plan_id}/pgs", headers=h).json()
    assert pg_id not in {r["id"] for r in rows}


def test_disabled_pg_is_not_listed(client, conn, new_pg):
    pg_id = new_pg()
    conn.execute("UPDATE pgs SET status = 'disabled' WHERE id = %s", (pg_id,))
    conn.commit()
    h, plan_id = plan_for(client, "listing-user-2")
    listed = client.get(f"/v1/plans/{plan_id}/pgs", headers=h).json()
    assert pg_id not in {r["id"] for r in listed}


def test_a_pg_without_consent_cannot_be_put_in_a_batch(client, conn, new_pg):
    pg_id = new_pg()
    revoke(conn, pg_id)
    h, plan_id = plan_for(client, "batch-user-1")
    res = client.post(f"/v1/plans/{plan_id}/call-batches", json={"pg_ids": [pg_id]}, headers=h)
    assert res.status_code == 422


def test_no_call_can_start_before_the_mover_approves(client, make_call, conn):
    c = make_call(approve=False)
    call = conn.execute("SELECT id FROM calls WHERE batch_id = %s", (c.batch_id,)).fetchone()
    with pytest.raises(CallBlocked) as blocked:
        check_call_allowed(conn, call["id"])
    assert blocked.value.reason == "not_approved"
    res = client.post(f"/v1/calls/{call['id']}/web-session", headers=c.headers)
    assert res.status_code == 409


def test_approval_allows_the_call_and_is_audited(make_call, conn):
    c = make_call()
    assert check_call_allowed(conn, c.call_id).pg_id is not None
    audit = conn.execute(
        "SELECT 1 FROM audit_events WHERE action = 'call_batch_approved' AND object_id = %s",
        (c.batch_id,),
    ).fetchone()
    assert audit is not None


def test_a_batch_cannot_be_approved_twice(client, make_call):
    c = make_call()
    again = client.post(f"/v1/call-batches/{c.batch_id}/approve", headers=c.headers)
    assert again.status_code == 409


def test_another_user_cannot_approve_or_read_the_batch_or_call(client, make_call):
    c = make_call(approve=False)
    other = sign_in(client, "intruder-user-1")
    assert client.post(f"/v1/call-batches/{c.batch_id}/approve", headers=other).status_code == 404
    c2 = make_call()
    assert client.get(f"/v1/calls/{c2.call_id}", headers=other).status_code == 404
    assert client.post(f"/v1/calls/{c2.call_id}/web-session", headers=other).status_code == 404


def test_consent_lost_before_approval_skips_that_pg(client, make_call, conn):
    c = make_call(approve=False)
    revoke(conn, c.pg_id)
    res = client.post(f"/v1/call-batches/{c.batch_id}/approve", headers=c.headers).json()
    assert res["calls"] == [] and len(res["skipped"]) == 1


def test_a_pg_is_not_called_twice_for_one_plan(client, make_call):
    c = make_call()
    again = client.post(
        f"/v1/plans/{c.plan_id}/call-batches", json={"pg_ids": [c.pg_id]}, headers=c.headers
    )
    assert again.status_code == 409


def test_phone_calls_are_blocked_while_calling_is_disabled(make_call, conn, monkeypatch):
    c = make_call()
    conn.execute("UPDATE calls SET provider = 'exotel' WHERE id = %s", (c.call_id,))
    conn.commit()
    monkeypatch.setenv("CALLING_ENABLED", "false")
    with pytest.raises(CallBlocked) as blocked:
        check_call_allowed(conn, c.call_id)
    assert blocked.value.reason == "calling_disabled"


def test_web_session_token_is_for_exactly_one_call(client, make_call):
    c = make_call()
    token = client.post(f"/v1/calls/{c.call_id}/web-session", headers=c.headers).json()["token"]
    assert call_token.verify(token, c.call_id)
    with pytest.raises(call_token.TokenError):
        call_token.verify(token, uuid4())
    with pytest.raises(call_token.TokenError):
        call_token.verify(token + "x", c.call_id)


def test_read_call_returns_facts_with_offsets(client, make_call, conn):
    c = make_call()
    conn.execute(
        "INSERT INTO call_facts (call_id, field, value, confirmed, transcript_offset)"
        " VALUES (%s, 'rent', '\"12000\"', true, 4200)",
        (c.call_id,),
    )
    conn.commit()
    body = client.get(f"/v1/calls/{c.call_id}", headers=c.headers).json()
    assert body["facts"] == [
        {
            "field": "rent",
            "value": "12000",
            "confirmed": True,
            "transcript_offset": 4200,
            "quote": None,
            "source": None,
        }
    ]


def test_unknown_fact_fields_are_rejected_by_the_database(conn, make_call):
    c = make_call()
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO call_facts (call_id, field, value) VALUES (%s, 'bank_account', '\"x\"')",
            (c.call_id,),
        )
    conn.rollback()
