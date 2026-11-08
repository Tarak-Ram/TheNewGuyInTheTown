from conftest import PLAN, sign_in


def test_unauthenticated_requests_are_rejected(client):
    assert client.post("/v1/plans", json=PLAN).status_code == 401
    assert client.get("/v1/me").status_code == 401
    bad = {"Authorization": "Bearer not-a-real-token"}
    assert client.get("/v1/me", headers=bad).status_code == 401


def test_bad_google_token_is_rejected(client):
    res = client.post("/v1/auth/google", json={"id_token": "forged-token-value"})
    assert res.status_code == 401


def test_user_can_create_and_read_own_plan(client):
    alice = sign_in(client, "alice")
    created = client.post("/v1/plans", json=PLAN, headers=alice)
    assert created.status_code == 201
    got = client.get(f"/v1/plans/{created.json()['id']}", headers=alice)
    assert got.status_code == 200
    assert got.json()["office_address"] == PLAN["office_address"]
    assert got.json()["needs"]["food"] == "veg"


def test_user_cannot_read_another_users_plan(client):
    alice, bob = sign_in(client, "alice2"), sign_in(client, "bob2")
    plan_id = client.post("/v1/plans", json=PLAN, headers=alice).json()["id"]
    res = client.get(f"/v1/plans/{plan_id}", headers=bob)
    assert res.status_code == 404
    assert plan_id not in res.text


def test_missing_and_foreign_plans_look_identical(client):
    alice, bob = sign_in(client, "alice3"), sign_in(client, "bob3")
    plan_id = client.post("/v1/plans", json=PLAN, headers=alice).json()["id"]
    foreign = client.get(f"/v1/plans/{plan_id}", headers=bob)
    missing = client.get("/v1/plans/00000000-0000-0000-0000-000000000000", headers=bob)
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


def test_sign_in_twice_returns_same_user(client):
    first = client.post("/v1/auth/google", json={"id_token": "google-carol"}).json()
    second = client.post("/v1/auth/google", json={"id_token": "google-carol"}).json()
    assert first["user"]["id"] == second["user"]["id"]


def test_deleted_user_session_stops_working(client, conn):
    headers = sign_in(client, "dave")
    assert client.get("/v1/me", headers=headers).status_code == 200
    conn.execute("UPDATE users SET deleted_at = now() WHERE email = 'dave@example.com'")
    conn.commit()
    assert client.get("/v1/me", headers=headers).status_code == 401
    # and signing in again must not revive the deleted account
    assert client.post("/v1/auth/google", json={"id_token": "google-dave"}).status_code == 403


def test_invalid_budget_is_rejected(client):
    alice = sign_in(client, "erin")
    bad = {**PLAN, "budget_min": 20000, "budget_max": 5000}
    assert client.post("/v1/plans", json=bad, headers=alice).status_code == 422


def test_plan_creation_is_audited(client, conn):
    alice = sign_in(client, "frank")
    plan_id = client.post("/v1/plans", json=PLAN, headers=alice).json()["id"]
    row = conn.execute(
        "SELECT 1 FROM audit_events WHERE action = 'plan_created' AND object_id = %s", (plan_id,)
    ).fetchone()
    assert row is not None
