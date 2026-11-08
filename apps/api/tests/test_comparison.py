from nguit_tools.extraction import extract_and_save
from nguit_tools.extractors import RuleExtractor
from psycopg.types.json import Jsonb

from conftest import sign_in

FIELDS = ["rent", "deposit", "food", "availability", "sharing_type", "rules", "notice_period"]

TRANSCRIPT = [
    ("agent", 0, "Hello, this is an AI assistant from The New Guy in Town. What is the rent?"),
    ("owner", 5000, "Rent is twelve thousand per month. Deposit is around twenty thousand."),
    ("agent", 12000, "Is food included?"),
    ("owner", 15000, "Breakfast and dinner are included. Notice period is 30 days."),
]


def finish_call(conn, call_id, transcript=TRANSCRIPT, status="completed"):
    for speaker, offset, text in transcript:
        conn.execute(
            "INSERT INTO transcript_segments (call_id, speaker, offset_ms, text)"
            " VALUES (%s, %s, %s, %s)",
            (call_id, speaker, offset, text),
        )
    conn.execute(
        "UPDATE calls SET status = %s, started_at = now(), ended_at = now() WHERE id = %s",
        (status, call_id),
    )
    conn.commit()


def facts_by_field(conn, call_id):
    rows = conn.execute("SELECT * FROM call_facts WHERE call_id = %s", (call_id,)).fetchall()
    return {r["field"]: r for r in rows}


def cells(client, c):
    body = client.get(f"/v1/plans/{c.plan_id}/comparison", headers=c.headers).json()
    return body, body["rows"][0]["fields"] if body["rows"] else {}


# -- saving --------------------------------------------------------------------------------
def test_only_verified_facts_are_saved_as_confirmed_with_source_and_offset(make_call, conn):
    c = make_call()
    finish_call(conn, c.call_id)
    extract_and_save(conn, c.call_id, RuleExtractor())
    conn.commit()
    f = facts_by_field(conn, c.call_id)

    assert set(f) == set(FIELDS)  # one row per field, always
    assert f["rent"]["confirmed"] and f["rent"]["value"] == 12000
    assert f["rent"]["transcript_offset"] == 5000 and f["rent"]["source"] == "transcript"
    assert "twelve thousand" in f["rent"]["quote"]
    assert (
        f["notice_period"]["value"] == "30 days"
        and f["notice_period"]["transcript_offset"] == 15000
    )
    # hedged ("around twenty thousand") and never-discussed fields stay unconfirmed and empty
    assert not f["deposit"]["confirmed"] and f["deposit"]["value"] is None
    assert not f["availability"]["confirmed"] and f["availability"]["value"] is None


def test_extraction_can_be_run_again_without_duplicating_anything(make_call, conn):
    c = make_call()
    finish_call(conn, c.call_id)
    extract_and_save(conn, c.call_id, RuleExtractor())
    extract_and_save(conn, c.call_id, RuleExtractor())
    conn.commit()
    n = conn.execute("SELECT count(*) AS n FROM call_facts WHERE call_id = %s", (c.call_id,))
    assert n.fetchone()["n"] == 7
    call = conn.execute("SELECT extracted_at, extractor FROM calls WHERE id=%s", (c.call_id,))
    row = call.fetchone()
    assert row["extracted_at"] is not None and row["extractor"] == "rules-v1"


def test_live_facts_the_transcript_does_not_support_are_replaced_and_counted(make_call, conn):
    c = make_call()
    finish_call(conn, c.call_id)
    conn.execute(
        "INSERT INTO call_facts (call_id, field, value, confirmed, transcript_offset)"
        " VALUES (%s, 'rent', %s, true, 100)",
        (c.call_id, Jsonb("99999")),  # the model claimed this during the call
    )
    conn.commit()
    extract_and_save(conn, c.call_id, RuleExtractor())
    conn.commit()
    assert facts_by_field(conn, c.call_id)["rent"]["value"] == 12000  # transcript wins
    audit = conn.execute(
        "SELECT metadata FROM audit_events WHERE action='facts_extracted' AND object_id=%s",
        (str(c.call_id),),
    ).fetchone()
    assert audit["metadata"]["extractor"] == "rules-v1"


def test_a_call_with_no_transcript_confirms_nothing(make_call, conn):
    c = make_call()
    conn.execute("UPDATE calls SET status='unreachable', ended_at=now() WHERE id=%s", (c.call_id,))
    conn.commit()
    extract_and_save(conn, c.call_id, RuleExtractor())
    conn.commit()
    assert not any(r["confirmed"] for r in facts_by_field(conn, c.call_id).values())


# -- comparison table ------------------------------------------------------------------------
def test_unknown_values_show_not_confirmed(client, make_call, conn):
    c = make_call()
    finish_call(conn, c.call_id)
    extract_and_save(conn, c.call_id, RuleExtractor())
    conn.commit()
    body, f = cells(client, c)
    assert body["field_order"] == FIELDS
    assert f["rent"]["display"] == "Rs 12,000" and f["rent"]["confirmed"]
    assert f["food"]["display"] == "included: breakfast, dinner"
    assert f["deposit"] == {
        "value": None, "confirmed": False, "display": "Not confirmed",
        "transcript_offset": None, "quote": None,
    }  # fmt: skip
    assert f["availability"]["display"] == "Not confirmed"


def test_live_model_facts_are_not_shown_as_confirmed_before_the_transcript_check(
    client, make_call, conn
):
    c = make_call()
    finish_call(conn, c.call_id)
    conn.execute(
        "INSERT INTO call_facts (call_id, field, value, confirmed, transcript_offset)"
        " VALUES (%s, 'rent', %s, true, 100)",
        (c.call_id, Jsonb("12000")),
    )
    conn.commit()
    body, f = cells(client, c)
    assert body["rows"][0]["facts_checked"] is False
    assert f["rent"]["display"] == "Not confirmed" and f["rent"]["value"] is None


def test_each_value_carries_the_transcript_moment_it_came_from(client, make_call, conn):
    c = make_call()
    finish_call(conn, c.call_id)
    extract_and_save(conn, c.call_id, RuleExtractor())
    conn.commit()
    _, f = cells(client, c)
    assert f["rent"]["transcript_offset"] == 5000 and "twelve thousand" in f["rent"]["quote"]


def test_pg_that_was_not_reached_shows_every_field_as_not_confirmed(client, make_call, conn):
    c = make_call()
    conn.execute("UPDATE calls SET status='unreachable', ended_at=now() WHERE id=%s", (c.call_id,))
    conn.commit()
    body, f = cells(client, c)
    assert body["rows"][0]["call_status"] == "unreachable"
    assert all(cell["display"] == "Not confirmed" for cell in f.values())


def test_pending_batches_do_not_appear_in_the_table(client, make_call):
    c = make_call(approve=False)
    body = client.get(f"/v1/plans/{c.plan_id}/comparison", headers=c.headers).json()
    assert body["rows"] == []


def test_a_user_cannot_read_another_users_comparison(client, make_call, conn):
    c = make_call()
    finish_call(conn, c.call_id)
    other = sign_in(client, "comparison-intruder")
    assert client.get(f"/v1/plans/{c.plan_id}/comparison", headers=other).status_code == 404
    assert client.get(f"/v1/plans/{c.plan_id}/comparison").status_code == 401


# -- extract endpoint --------------------------------------------------------------------------
def test_extract_endpoint_rejects_unfinished_calls(client, make_call):
    c = make_call()
    res = client.post(f"/v1/calls/{c.call_id}/extract", headers=c.headers)
    assert res.status_code == 409


def test_extract_endpoint_saves_facts_and_is_owner_only(client, make_call, conn):
    c = make_call()
    finish_call(conn, c.call_id)
    other = sign_in(client, "extract-intruder")
    assert client.post(f"/v1/calls/{c.call_id}/extract", headers=other).status_code == 404
    res = client.post(f"/v1/calls/{c.call_id}/extract", headers=c.headers)
    assert res.status_code == 200
    facts = {f["field"]: f for f in res.json()["facts"]}
    assert facts["rent"]["value"] == 12000 and facts["rent"]["source"] == "transcript"
