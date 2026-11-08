import importlib.util
import os
from pathlib import Path

import pytest
from relocation_api.seed import seed

from conftest import PLAN, sign_in

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def reset_demo():
    """Loads scripts/reset_demo.py without letting its .env loading leak into the tests."""
    before = dict(os.environ)
    spec = importlib.util.spec_from_file_location("reset_demo", ROOT / "scripts" / "reset_demo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    os.environ.clear()
    os.environ.update(before)
    return module


@pytest.fixture
def demo(client, conn, monkeypatch, reset_demo):
    """A seeded database, DEMO_MODE on, and no real file or docker calls."""
    monkeypatch.setenv("DEMO_MODE", "true")
    seed(conn)
    conn.commit()
    removed: list[str] = []
    monkeypatch.setattr(reset_demo, "delete_uploaded_files", removed.extend)
    reset_demo.removed = removed
    return reset_demo


def demo_headers(client):
    token = client.post("/v1/auth/demo").json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_it_refuses_to_run_outside_demo_mode(reset_demo, monkeypatch):
    for value in ("", "false", "0"):
        monkeypatch.setenv("DEMO_MODE", value)
        with pytest.raises(SystemExit):
            reset_demo.refuse_unless_demo()
    monkeypatch.setenv("DEMO_MODE", "true")
    reset_demo.refuse_unless_demo()  # fine


def test_it_removes_the_demo_users_data_and_nobody_elses(client, conn, demo):
    mine = demo_headers(client)
    other = sign_in(client, "real-user-reset-1")
    demo_plan = client.post("/v1/plans", json=PLAN, headers=mine).json()["id"]
    other_plan = client.post("/v1/plans", json=PLAN, headers=other).json()["id"]
    agreement = client.post(
        "/v1/agreements",
        json={
            "plan_id": demo_plan,
            "filename": "a.pdf",
            "content_type": "application/pdf",
            "size_bytes": 10,
        },
        headers=mine,
    ).json()

    wiped = demo.wipe_demo_user(conn)
    conn.commit()

    assert wiped == {"plans": 1, "agreements": 1}
    assert client.get(f"/v1/plans/{demo_plan}", headers=mine).status_code == 404
    assert client.get(f"/v1/plans/{other_plan}", headers=other).status_code == 200  # untouched
    assert len(demo.removed) == 1 and demo.removed[0].startswith(agreement["id"])


def test_it_does_nothing_when_there_is_no_demo_user_yet(conn, demo):
    demo.wipe_demo_user(conn)  # clear anything earlier tests left behind
    conn.execute(
        "DELETE FROM audit_events"
        " WHERE actor IN (SELECT id::text FROM users WHERE google_sub = 'demo-user')"
    )
    conn.execute("DELETE FROM users WHERE google_sub = 'demo-user'")
    conn.commit()
    assert demo.wipe_demo_user(conn) == {"plans": 0, "agreements": 0}


def test_pgs_that_opted_out_are_callable_again(conn, demo):
    pgs = conn.execute(
        "SELECT id FROM pgs WHERE name ~ %s ORDER BY name LIMIT 2", (demo.SEED_PG_PATTERN,)
    ).fetchall()
    conn.execute("UPDATE consents SET revoked_at = now() WHERE subject_id = %s", (pgs[0]["id"],))
    conn.execute("UPDATE pgs SET status = 'disabled' WHERE id = %s", (pgs[1]["id"],))
    conn.commit()

    restored = demo.restore_sample_pgs(conn)
    conn.commit()

    from nguit_tools.call_gate import pg_is_callable

    assert restored >= 1
    assert pg_is_callable(conn, pgs[0]["id"]) and pg_is_callable(conn, pgs[1]["id"])


def test_sample_calls_fill_the_comparison_table_through_the_real_checks(client, conn, demo):
    demo.wipe_demo_user(conn)
    assert demo.add_sample_calls(conn) == 3
    conn.commit()

    headers = demo_headers(client)
    plan_id = client.get("/v1/plans", headers=headers).json()[0]["id"]
    rows = client.get(f"/v1/plans/{plan_id}/comparison", headers=headers).json()["rows"]
    by_name = {r["pg_name"]: r for r in rows}

    assert len(rows) == 3 and all(r["provider"] == "sample" for r in rows)
    clear = by_name["TEST PG 03 (fake)"]["fields"]
    assert clear["rent"]["display"] == "Rs 12,000" and clear["deposit"]["display"] == "Rs 24,000"
    assert clear["food"]["display"] == "included: breakfast, dinner"
    assert clear["notice_period"]["display"] == "30 days"
    assert clear["rules"]["display"] == "no smoking; no alcohol"

    unsure = by_name["TEST PG 04 (fake)"]["fields"]
    assert unsure["rent"]["display"] == "Not confirmed"  # "around eleven thousand, maybe"
    assert unsure["deposit"]["display"] == "Not confirmed"  # "two months rent"
    assert unsure["availability"]["display"] == "immediately"

    stopped = by_name["TEST PG 06 (fake)"]
    assert (
        stopped["call_status"] == "opted_out"
        and stopped["fields"]["rent"]["display"] == "Rs 14,000"
    )
    assert stopped["fields"]["food"]["display"] == "Not confirmed"


def test_running_it_twice_gives_the_same_clean_result(client, conn, demo):
    for _ in range(2):
        demo.wipe_demo_user(conn)
        demo.restore_sample_pgs(conn)
        demo.add_sample_calls(conn)
        conn.commit()
    headers = demo_headers(client)
    plans = client.get("/v1/plans", headers=headers).json()
    assert len(plans) == 1
    rows = client.get(f"/v1/plans/{plans[0]['id']}/comparison", headers=headers).json()["rows"]
    assert len(rows) == 3
