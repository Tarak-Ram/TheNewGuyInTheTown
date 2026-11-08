"""Two guarantees that a race or a repeated request must not be able to break.

1. One live call per PG per mover. Two requests at the same moment used to both pass the check
   and both create a call, so an owner could be called twice.
2. A call link works once. A second link used to be issuable while the call was running, which
   allowed two sessions on one call.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from fastapi.testclient import TestClient
from nguit_tools import call_token
from relocation_api.main import app
from voice_gateway.store import CallStore

from conftest import PLAN, sign_in


def mint(client, c):
    return client.post(f"/v1/calls/{c.call_id}/web-session", headers=c.headers)


def set_status(conn, call_id, status):
    conn.execute(
        "UPDATE calls SET status = %s, token_used_at = now() WHERE id = %s", (status, call_id)
    )
    conn.commit()


# -- a call link works once ---------------------------------------------------------------------
@pytest.mark.parametrize("status", ["connecting", "in_progress"])
def test_no_new_link_can_be_issued_while_the_call_is_running(client, make_call, conn, status):
    c = make_call()
    assert mint(client, c).status_code == 200
    set_status(conn, c.call_id, status)

    again = mint(client, c)

    assert again.status_code == 409
    row = conn.execute("SELECT token_used_at FROM calls WHERE id = %s", (c.call_id,)).fetchone()
    assert row["token_used_at"] is not None  # the used link was not reset to "unused"


def test_a_new_link_can_be_requested_until_the_first_one_is_used(client, make_call, conn):
    c = make_call()
    first, second = mint(client, c), mint(client, c)
    assert first.status_code == second.status_code == 200
    stored = conn.execute("SELECT token_jti_hash FROM calls WHERE id = %s", (c.call_id,)).fetchone()
    new_jti = call_token.verify(second.json()["token"], c.call_id)
    old_jti = call_token.verify(first.json()["token"], c.call_id)
    assert stored["token_jti_hash"] == call_token.hash_jti(new_jti)
    assert stored["token_jti_hash"] != call_token.hash_jti(old_jti)  # the older link is dead


async def test_the_gateway_itself_refuses_a_link_for_a_call_that_is_not_approved(
    client, make_call, conn
):
    c = make_call()
    jti = call_token.verify(mint(client, c).json()["token"], c.call_id)
    conn.execute("UPDATE calls SET status = 'in_progress' WHERE id = %s", (c.call_id,))
    conn.commit()
    assert await CallStore(c.call_id).claim_token(call_token.hash_jti(jti)) is False


# -- one live call per PG per mover ---------------------------------------------------------------
def post_batch(headers, plan_id, pg_id):
    with TestClient(app) as own:  # each thread has its own client
        return own.post(
            f"/v1/plans/{plan_id}/call-batches", json={"pg_ids": [pg_id]}, headers=headers
        ).status_code


def live_calls(conn, plan_id, pg_id):
    return conn.execute(
        "SELECT count(*) AS n FROM calls c JOIN call_batches b ON b.id = c.batch_id"
        " WHERE b.plan_id = %s AND c.pg_id = %s AND c.status NOT IN ('failed', 'unreachable')",
        (plan_id, pg_id),
    ).fetchone()["n"]


def test_simultaneous_requests_create_exactly_one_call(client, conn, new_pg):
    headers = sign_in(client, "race-user-one")
    plan_id = client.post("/v1/plans", json=PLAN, headers=headers).json()["id"]
    pg_id = new_pg()

    with ThreadPoolExecutor(8) as pool:
        codes = list(pool.map(lambda _: post_batch(headers, plan_id, pg_id), range(8)))

    assert codes.count(201) == 1, codes
    assert codes.count(409) == 7, codes
    assert live_calls(conn, plan_id, pg_id) == 1


def test_the_database_itself_refuses_two_live_calls_for_one_pg_and_plan(client, conn, new_pg):
    headers = sign_in(client, "race-user-two")
    plan_id = client.post("/v1/plans", json=PLAN, headers=headers).json()["id"]
    pg_id = new_pg()
    first = client.post(
        f"/v1/plans/{plan_id}/call-batches", json={"pg_ids": [pg_id]}, headers=headers
    )
    assert first.status_code == 201
    other_batch = conn.execute(
        "INSERT INTO call_batches (plan_id) VALUES (%s) RETURNING id", (plan_id,)
    ).fetchone()
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute(
            "INSERT INTO calls (batch_id, pg_id, plan_id, status)"
            " VALUES (%s, %s, %s, 'pending_approval')",
            (other_batch["id"], pg_id, plan_id),
        )
    conn.rollback()


def test_a_failed_call_does_not_block_one_retry(client, conn, new_pg):
    headers = sign_in(client, "race-user-three")
    plan_id = client.post("/v1/plans", json=PLAN, headers=headers).json()["id"]
    pg_id = new_pg()
    client.post(f"/v1/plans/{plan_id}/call-batches", json={"pg_ids": [pg_id]}, headers=headers)
    conn.execute(
        "UPDATE calls SET status = 'unreachable', ended_at = now() WHERE batch_id IN"
        " (SELECT id FROM call_batches WHERE plan_id = %s)",
        (plan_id,),
    )
    conn.commit()

    retry = client.post(
        f"/v1/plans/{plan_id}/call-batches", json={"pg_ids": [pg_id]}, headers=headers
    )
    assert retry.status_code == 201  # one retry after an unreachable call
    third = client.post(
        f"/v1/plans/{plan_id}/call-batches", json={"pg_ids": [pg_id]}, headers=headers
    )
    assert third.status_code == 409  # but not two live calls at once


def test_different_movers_can_each_call_the_same_pg(client, new_pg):
    pg_id = new_pg()
    for name in ("race-user-four", "race-user-five"):
        headers = sign_in(client, name)
        plan_id = client.post("/v1/plans", json=PLAN, headers=headers).json()["id"]
        res = client.post(
            f"/v1/plans/{plan_id}/call-batches", json={"pg_ids": [pg_id]}, headers=headers
        )
        assert res.status_code == 201


def test_the_batch_is_all_or_nothing_when_one_pg_is_already_taken(client, conn, new_pg):
    headers = sign_in(client, "race-user-six")
    plan_id = client.post("/v1/plans", json=PLAN, headers=headers).json()["id"]
    taken, free = new_pg(), new_pg()
    client.post(f"/v1/plans/{plan_id}/call-batches", json={"pg_ids": [taken]}, headers=headers)

    res = client.post(
        f"/v1/plans/{plan_id}/call-batches", json={"pg_ids": [free, taken]}, headers=headers
    )

    assert res.status_code == 409
    assert live_calls(conn, plan_id, free) == 0  # nothing was half-created


def test_the_race_cannot_be_won_by_asking_the_same_pg_twice_in_one_batch(client, conn, new_pg):
    headers = sign_in(client, "race-user-seven")
    plan_id = client.post("/v1/plans", json=PLAN, headers=headers).json()["id"]
    pg_id = new_pg()
    res = client.post(
        f"/v1/plans/{plan_id}/call-batches", json={"pg_ids": [pg_id, pg_id]}, headers=headers
    )
    assert res.status_code == 201 and len(res.json()["pgs"]) == 1
    assert live_calls(conn, plan_id, pg_id) == 1


def test_a_hundred_checks_per_second_cannot_slip_a_second_call_in(client, conn, new_pg):
    """Same race, much harder: 24 requests across 12 threads."""
    headers = sign_in(client, "race-user-eight")
    plan_id = client.post("/v1/plans", json=PLAN, headers=headers).json()["id"]
    pg_id = new_pg()
    with ThreadPoolExecutor(12) as pool:
        codes = list(pool.map(lambda _: post_batch(headers, plan_id, pg_id), range(24)))
    assert codes.count(201) == 1, codes
    assert live_calls(conn, plan_id, pg_id) == 1


async def test_nothing_in_the_gateway_depends_on_the_event_loop_state(client, make_call):
    """Guards the async test setup used above: the claim helper runs in its own thread."""
    c = make_call()
    jti = call_token.verify(mint(client, c).json()["token"], c.call_id)
    results = await asyncio.gather(
        *[CallStore(c.call_id).claim_token(call_token.hash_jti(jti)) for _ in range(6)]
    )
    assert results.count(True) == 1  # six at once, one winner
