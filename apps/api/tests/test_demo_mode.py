import pytest
from relocation_api.demo import DEMO_BASIS, DemoPlaces, DemoRoutes, km_between, use_demo_maps
from relocation_api.maps import AddressNotFound, LatLng, peak_departure
from relocation_api.seed import seed

from conftest import PLAN, sign_in


@pytest.fixture
def seeded(conn):
    seed(conn)
    conn.execute("DELETE FROM commute_cache")
    conn.commit()


# -- the switch --------------------------------------------------------------------------------
def test_demo_sign_in_does_not_exist_by_default(client):
    assert client.post("/v1/auth/demo").status_code == 404


@pytest.mark.parametrize("value", ["", "false", "0", "yes", "True ", "1"])
def test_only_the_word_true_turns_demo_mode_on(client, monkeypatch, value):
    monkeypatch.setenv("DEMO_MODE", value)
    expected = value.strip().lower() == "true"
    assert (client.post("/v1/auth/demo").status_code == 200) is expected


def test_demo_sign_in_gives_a_working_session_for_one_fixed_user(client, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    first = client.post("/v1/auth/demo").json()
    second = client.post("/v1/auth/demo").json()
    assert first["user"]["id"] == second["user"]["id"]
    assert first["user"]["email"] == "demo@example.com"
    headers = {"Authorization": f"Bearer {first['access_token']}"}
    assert client.get("/v1/me", headers=headers).json()["email"] == "demo@example.com"


def test_the_demo_session_cannot_read_another_users_plan(client, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    real = sign_in(client, "real-person-1")
    plan_id = client.post("/v1/plans", json=PLAN, headers=real).json()["id"]
    demo = {"Authorization": f"Bearer {client.post('/v1/auth/demo').json()['access_token']}"}
    assert client.get(f"/v1/plans/{plan_id}", headers=demo).status_code == 404


def test_demo_maps_are_used_only_without_a_real_key(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.delenv("MAPS_API_KEY", raising=False)
    assert use_demo_maps()
    monkeypatch.setenv("MAPS_API_KEY", "a-real-key")
    assert not use_demo_maps()  # a real key always wins
    monkeypatch.delenv("MAPS_API_KEY")
    monkeypatch.setenv("DEMO_MODE", "false")
    assert not use_demo_maps()


# -- demo addresses -------------------------------------------------------------------------------
@pytest.mark.parametrize("text", ["Wipro Circle", "wipro circle gachibowli", "Near Cyber Towers"])
def test_known_offices_are_found(text):
    address, point = DemoPlaces().find_address(text)
    assert "Hyderabad" in address and 17 < point.lat < 18


def test_unknown_addresses_are_not_invented():
    with pytest.raises(AddressNotFound):
        DemoPlaces().find_address("12 Some Random Street")


def test_validate_endpoint_in_demo_mode(client, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.delenv("MAPS_API_KEY", raising=False)
    h = sign_in(client, "demo-validate-1")
    ok = client.post("/v1/places/validate", json={"address": "Wipro Circle"}, headers=h)
    assert ok.status_code == 200 and ok.json()["lat"] == 17.4401
    bad = client.post("/v1/places/validate", json={"address": "12 Some Random Street"}, headers=h)
    assert bad.status_code == 422


# -- demo commute estimates ---------------------------------------------------------------------
def minutes(mode, origin):
    out = DemoRoutes().commute_minutes(
        {"x": origin}, LatLng(17.4401, 78.3489), mode, peak_departure()
    )
    return out["x"]


def test_estimates_grow_with_distance_and_depend_on_how_you_travel():
    near, far = LatLng(17.4420, 78.3500), LatLng(17.5000, 78.4000)
    assert minutes("car", near) < minutes("car", far)
    assert minutes("bike", far) < minutes("car", far)  # a bike beats peak-hour traffic
    assert minutes("public", far) > minutes("car", far)


def test_distance_helper_is_sane():
    assert km_between(LatLng(17.44, 78.35), LatLng(17.44, 78.35)) == 0
    assert 5 < km_between(LatLng(17.40, 78.35), LatLng(17.44, 78.40)) < 10


def test_ranking_in_demo_mode_is_labelled_as_demo_data(client, seeded, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.delenv("MAPS_API_KEY", raising=False)
    h = sign_in(client, "demo-rank-user")
    plan = {**PLAN, "office_lat": 17.4401, "office_lng": 78.3489}
    plan_id = client.post("/v1/plans", json=plan, headers=h).json()["id"]
    res = client.post(f"/v1/plans/{plan_id}/rank-areas", headers=h)
    assert res.status_code == 200
    body = res.json()
    assert body["commute_basis"] == DEMO_BASIS and "not live Google Maps" in body["commute_basis"]
    assert 3 <= len(body["areas"]) <= 5
    shortest = min(body["areas"], key=lambda a: a["commute_minutes"])
    assert shortest["name"] == "Gachibowli"  # the office is in Gachibowli
    assert "Gachibowli" in [a["name"] for a in body["areas"][:3]]
    assert client.get(f"/v1/plans/{plan_id}/areas", headers=h).json()["commute_basis"] == DEMO_BASIS


def test_demo_estimates_are_cached_separately_from_real_times(client, seeded, conn, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.delenv("MAPS_API_KEY", raising=False)
    h = sign_in(client, "demo-cache-user")
    plan_id = client.post("/v1/plans", json={**PLAN, "office_lat": 17.4402}, headers=h).json()["id"]
    client.post(f"/v1/plans/{plan_id}/rank-areas", headers=h)
    dayparts = {r["daypart"] for r in conn.execute("SELECT daypart FROM commute_cache").fetchall()}
    assert dayparts == {"demo_estimate"}


# -- listing plans (so the app can offer "continue") --------------------------------
def test_plans_list_shows_only_my_plans_newest_first(client):
    mine, other = sign_in(client, "list-owner-1"), sign_in(client, "list-other-1")
    first = client.post("/v1/plans", json=PLAN, headers=mine).json()["id"]
    second = client.post("/v1/plans", json={**PLAN, "budget_max": 15000}, headers=mine).json()["id"]
    client.post("/v1/plans", json=PLAN, headers=other)
    listed = [p["id"] for p in client.get("/v1/plans", headers=mine).json()]
    assert listed == [second, first]
    assert client.get("/v1/plans").status_code == 401
