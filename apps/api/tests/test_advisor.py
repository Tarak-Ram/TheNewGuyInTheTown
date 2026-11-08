from datetime import UTC, datetime

import pytest
from relocation_api.advisor import get_places_client, get_routes_client
from relocation_api.explain import get_explainer
from relocation_api.main import app
from relocation_api.maps import (
    AddressNotFound,
    LatLng,
    MapsError,
    RoutesClient,
    peak_departure,
)
from relocation_api.seed import AREAS, seed

from conftest import PLAN, sign_in

# Distinct office per test so cached commute rows never leak between tests.
_counter = {"n": 0}


def fresh_plan(**over):
    _counter["n"] += 1
    return {**PLAN, "office_lat": 17.40 + _counter["n"] * 0.001, **over}


class FakeRoutes:
    """Stands in for Google Routes. Records calls so tests can check caching."""

    def __init__(self, minutes_by_name=None, fail=False):
        self.calls = 0
        self.fail = fail
        self.minutes_by_name = minutes_by_name or {}

    def commute_minutes(self, origins, office, mode, departure):
        self.calls += 1
        if self.fail:
            raise MapsError("down")
        # origin keys are area ids; map them back to names through the database order
        return {k: self.minutes_by_name.get(k, 30) for k in origins}


class FakePlaces:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error

    def find_address(self, text):
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def seeded(conn):
    seed(conn)
    conn.execute("DELETE FROM commute_cache")
    conn.commit()
    return conn


def use(routes=None, places=None, explainer=None):
    if routes:
        app.dependency_overrides[get_routes_client] = lambda: routes
    if places:
        app.dependency_overrides[get_places_client] = lambda: places
    if explainer:
        app.dependency_overrides[get_explainer] = lambda: explainer


def make_plan(client, headers, **over):
    return client.post("/v1/plans", json=fresh_plan(**over), headers=headers).json()["id"]


def test_commute_numbers_come_from_the_routes_tool(client, seeded):
    ids = {r["name"]: str(r["id"]) for r in seeded.execute("SELECT id, name FROM areas")}
    routes = FakeRoutes({ids["Kondapur"]: 25, ids["Miyapur"]: 70})
    use(routes=routes)
    h = sign_in(client, "ann")
    res = client.post(f"/v1/plans/{make_plan(client, h)}/rank-areas", headers=h)
    assert res.status_code == 200, res.text
    by_name = {a["name"]: a for a in res.json()["areas"]}
    assert by_name["Kondapur"]["commute_minutes"] == 25
    assert len(res.json()["areas"]) == 5  # 3 to 5 areas
    assert routes.calls == 1


def test_every_area_shows_commute_rent_source_date_and_one_reason(client, seeded):
    use(routes=FakeRoutes())
    h = sign_in(client, "ben")
    res = client.post(f"/v1/plans/{make_plan(client, h)}/rank-areas", headers=h).json()
    for a in res["areas"]:
        assert a["commute_minutes"] > 0
        assert a["rent_min"] <= a["rent_max"]
        assert a["rent_source"] and a["rent_updated_at"]
        assert a["reason"].strip()
    assert res["explanation_source"] == "template"  # no model configured in tests


def test_closer_area_ranks_first_even_if_rent_is_higher(client, seeded):
    ids = {r["name"]: str(r["id"]) for r in seeded.execute("SELECT id, name FROM areas")}
    use(routes=FakeRoutes({ids["Gachibowli"]: 12, ids["Kukatpally"]: 70}))
    h = sign_in(client, "cat")
    areas = client.post(f"/v1/plans/{make_plan(client, h)}/rank-areas", headers=h).json()["areas"]
    names = [a["name"] for a in areas]
    assert names[0] == "Gachibowli"
    assert "Kukatpally" not in names[:2]


def test_second_ranking_uses_the_cache(client, seeded):
    routes = FakeRoutes()
    use(routes=routes)
    h = sign_in(client, "dan")
    plan_id = make_plan(client, h)
    client.post(f"/v1/plans/{plan_id}/rank-areas", headers=h)
    client.post(f"/v1/plans/{plan_id}/rank-areas", headers=h)
    assert routes.calls == 1


def test_routes_failure_gives_a_clear_error_and_no_guessed_numbers(client, seeded):
    use(routes=FakeRoutes(fail=True))
    h = sign_in(client, "eve")
    plan_id = make_plan(client, h)
    res = client.post(f"/v1/plans/{plan_id}/rank-areas", headers=h)
    assert res.status_code == 502
    assert "unavailable" in res.json()["detail"]
    assert client.get(f"/v1/plans/{plan_id}/areas", headers=h).json()["areas"] == []


def test_a_lying_model_cannot_change_commute_numbers(client, seeded):
    class LyingExplainer:
        def explain(self, scored):
            return {s.area.area_id: "Only 5 minutes away, great value!" for s in scored}

    use(routes=FakeRoutes(), explainer=LyingExplainer())
    h = sign_in(client, "fay")
    res = client.post(f"/v1/plans/{make_plan(client, h)}/rank-areas", headers=h).json()
    assert all(a["commute_minutes"] == 30 for a in res["areas"])
    assert all("5 minutes" not in a["reason"] for a in res["areas"])
    assert res["explanation_source"] == "template"


def test_a_good_model_explanation_is_used(client, seeded):
    class GoodExplainer:
        def explain(self, scored):
            return {s.area.area_id: "A short ride to your office." for s in scored}

    use(routes=FakeRoutes(), explainer=GoodExplainer())
    h = sign_in(client, "gus")
    res = client.post(f"/v1/plans/{make_plan(client, h)}/rank-areas", headers=h).json()
    assert res["explanation_source"] == "model"
    assert res["areas"][0]["reason"] == "A short ride to your office."


def test_a_broken_model_falls_back_to_the_template(client, seeded):
    class BrokenExplainer:
        def explain(self, scored):
            raise RuntimeError("model unavailable")

    use(routes=FakeRoutes(), explainer=BrokenExplainer())
    h = sign_in(client, "hal")
    res = client.post(f"/v1/plans/{make_plan(client, h)}/rank-areas", headers=h)
    assert res.status_code == 200
    assert res.json()["explanation_source"] == "template"


def test_no_budget_match_shows_closest_options_and_the_gap(client, seeded):
    use(routes=FakeRoutes())
    h = sign_in(client, "ian")
    plan_id = make_plan(client, h, budget_min=1000, budget_max=3000)
    res = client.post(f"/v1/plans/{plan_id}/rank-areas", headers=h).json()
    assert res["over_budget_all"] is True
    assert res["areas"]  # still shows the closest options
    assert all(a["budget_gap"] > 0 for a in res["areas"])


def test_areas_without_commute_data_are_skipped_and_listed(client, seeded):
    class PartialRoutes(FakeRoutes):
        def commute_minutes(self, origins, office, mode, departure):
            keys = list(origins)
            return {k: 30 for k in keys[:-1]}  # last area has no route

    use(routes=PartialRoutes())
    h = sign_in(client, "joanna")
    res = client.post(f"/v1/plans/{make_plan(client, h)}/rank-areas", headers=h).json()
    assert len(res["skipped_areas"]) == 1


def test_ranking_is_saved_and_can_be_read_back(client, seeded):
    use(routes=FakeRoutes())
    h = sign_in(client, "kim")
    plan_id = make_plan(client, h)
    ranked = client.post(f"/v1/plans/{plan_id}/rank-areas", headers=h).json()
    saved = client.get(f"/v1/plans/{plan_id}/areas", headers=h).json()
    assert [a["name"] for a in saved["areas"]] == [a["name"] for a in ranked["areas"]]


def test_user_cannot_rank_or_read_another_users_plan(client, seeded):
    routes = FakeRoutes()
    use(routes=routes)
    owner, other = sign_in(client, "lee"), sign_in(client, "max")
    plan_id = make_plan(client, owner)
    assert client.post(f"/v1/plans/{plan_id}/rank-areas", headers=other).status_code == 404
    assert client.get(f"/v1/plans/{plan_id}/areas", headers=other).status_code == 404
    assert routes.calls == 0  # no paid lookup was made for a plan that is not theirs


def test_profile_can_be_edited_and_old_scores_are_cleared(client, seeded):
    use(routes=FakeRoutes())
    h = sign_in(client, "nia")
    plan_id = make_plan(client, h)
    client.post(f"/v1/plans/{plan_id}/rank-areas", headers=h)
    edited = {**fresh_plan(), "budget_max": 20000, "needs": {"food": "non_veg"}}
    res = client.put(f"/v1/plans/{plan_id}", json=edited, headers=h)
    assert res.status_code == 200
    assert res.json()["budget_max"] == 20000
    assert res.json()["needs"]["food"] == "non_veg"
    assert client.get(f"/v1/plans/{plan_id}/areas", headers=h).json()["areas"] == []


def test_user_cannot_edit_another_users_plan(client):
    owner, other = sign_in(client, "oli"), sign_in(client, "pat")
    plan_id = make_plan(client, owner)
    res = client.put(f"/v1/plans/{plan_id}", json=fresh_plan(), headers=other)
    assert res.status_code == 404


def test_office_outside_hyderabad_is_rejected(client):
    h = sign_in(client, "quin")
    res = client.post("/v1/plans", json=fresh_plan(office_lat=28.6, office_lng=77.2), headers=h)
    assert res.status_code == 422


def test_invalid_address_shows_an_error(client):
    use(places=FakePlaces(error=AddressNotFound("zzz")))
    h = sign_in(client, "rae")
    res = client.post("/v1/places/validate", json={"address": "zzzz nowhere"}, headers=h)
    assert res.status_code == 422
    assert "could not find" in res.json()["detail"]


def test_valid_address_returns_coordinates(client):
    use(places=FakePlaces(result=("Wipro Circle, Hyderabad", LatLng(17.44, 78.35))))
    h = sign_in(client, "sam")
    res = client.post("/v1/places/validate", json={"address": "Wipro Circle"}, headers=h)
    assert res.status_code == 200
    assert res.json() == {
        "formatted_address": "Wipro Circle, Hyderabad",
        "lat": 17.44,
        "lng": 78.35,
    }


def test_address_outside_hyderabad_is_rejected(client):
    use(places=FakePlaces(result=("Delhi", LatLng(28.6, 77.2))))
    h = sign_in(client, "tia")
    res = client.post("/v1/places/validate", json={"address": "Connaught Place"}, headers=h)
    assert res.status_code == 422


def test_address_check_needs_sign_in(client):
    res = client.post("/v1/places/validate", json={"address": "anything"})
    assert res.status_code == 401


def test_places_outage_is_a_clear_502(client):
    use(places=FakePlaces(error=MapsError("down")))
    h = sign_in(client, "uma")
    res = client.post("/v1/places/validate", json={"address": "Madhapur"}, headers=h)
    assert res.status_code == 502


def test_peak_departure_is_a_future_weekday_nine_am_ist():
    saturday_noon = datetime(2026, 11, 14, 6, 30, tzinfo=UTC)  # Saturday 12:00 IST
    d = peak_departure(saturday_noon)
    assert d.weekday() == 0 and d.hour == 9 and d > saturday_noon  # Monday 9:00
    friday_evening = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
    assert peak_departure(friday_evening).weekday() == 0
    monday_early = datetime(2026, 11, 9, 1, 0, tzinfo=UTC)  # Monday 06:30 IST
    assert peak_departure(monday_early).day == 9


class FakeHttp:
    def __init__(self, payload=None, error=None):
        self.payload, self.error = payload, error

    def post(self, url, json=None, headers=None):
        if self.error:
            raise self.error
        outer = self

        class R:
            def raise_for_status(self):
                pass

            def json(self):
                return outer.payload

        return R()


def test_routes_client_parses_durations_and_rounds_up():
    http = FakeHttp(
        [
            {
                "originIndex": 0,
                "destinationIndex": 0,
                "duration": "1501s",
                "condition": "ROUTE_EXISTS",
            },
            {"originIndex": 1, "destinationIndex": 0, "condition": "ROUTE_NOT_FOUND"},
        ]
    )
    client = RoutesClient(api_key="k", http=http)
    out = client.commute_minutes(
        {"a": LatLng(17.4, 78.4), "b": LatLng(17.5, 78.4)},
        LatLng(17.44, 78.35),
        "car",
        peak_departure(),
    )
    assert out == {"a": 26}  # 1501 s is 25.02 minutes, rounded up; the no-route origin is dropped


def test_routes_client_raises_on_http_error_and_missing_key():
    import httpx

    bad = RoutesClient(api_key="k", http=FakeHttp(error=httpx.ConnectError("x")))
    with pytest.raises(MapsError):
        bad.commute_minutes(
            {"a": LatLng(17.4, 78.4)}, LatLng(17.44, 78.35), "car", peak_departure()
        )
    with pytest.raises(MapsError):
        RoutesClient(api_key="").commute_minutes({}, LatLng(17.4, 78.4), "car", peak_departure())


def test_seed_areas_are_all_ranked_candidates(seeded):
    assert seeded.execute("SELECT count(*) AS n FROM areas").fetchone()["n"] == len(AREAS)
