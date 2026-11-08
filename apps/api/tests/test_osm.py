import httpx
import pytest
from relocation_api.maps import AddressNotFound, LatLng, MapsError, peak_departure
from relocation_api.osm import OsmPlaces, OsmRoutes


class FakeHttp:
    def __init__(self, payload=None, error=None):
        self.payload, self.error, self.calls = payload, error, []

    def get(self, url, params=None):
        self.calls.append((url, params))
        if self.error:
            raise self.error
        payload = self.payload

        class R:
            def raise_for_status(self):
                pass

            def json(self):
                return payload

        return R()


def test_osm_routes_applies_peak_factor_and_drops_unroutable():
    http = FakeHttp({"code": "Ok", "durations": [[600], [None]]})
    out = OsmRoutes(http=http).commute_minutes(
        {"a": LatLng(17.4, 78.4), "b": LatLng(17.5, 78.4)},
        LatLng(17.44, 78.35),
        "car",
        peak_departure(),
    )
    assert out == {"a": 16}  # 10 min x 1.6 peak allowance; the origin with no route is dropped
    assert "78.4,17.4;78.4,17.5;78.35,17.44" in http.calls[0][0]


def test_osm_routes_raises_on_error():
    bad = OsmRoutes(http=FakeHttp(error=httpx.ConnectError("x")))
    with pytest.raises(MapsError):
        bad.commute_minutes(
            {"a": LatLng(17.4, 78.4)}, LatLng(17.44, 78.35), "car", peak_departure()
        )
    with pytest.raises(MapsError):
        OsmRoutes(http=FakeHttp({"code": "NoRoute"})).commute_minutes(
            {"a": LatLng(17.4, 78.4)}, LatLng(17.44, 78.35), "car", peak_departure()
        )


def test_osm_places_finds_and_misses():
    hit = FakeHttp([{"display_name": "Gachibowli, Hyderabad", "lat": "17.44", "lon": "78.35"}])
    assert OsmPlaces(http=hit).find_address("Gachibowli") == (
        "Gachibowli, Hyderabad",
        LatLng(17.44, 78.35),
    )
    with pytest.raises(AddressNotFound):
        OsmPlaces(http=FakeHttp([])).find_address("nowhere")
    with pytest.raises(MapsError):
        OsmPlaces(http=FakeHttp(error=httpx.ConnectError("x"))).find_address("x")
