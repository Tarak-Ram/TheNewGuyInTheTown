"""Google Maps Platform clients: Routes API (commute) and Places API (address check).

Commute minutes come from here and nowhere else. The language model never supplies them.
Endpoints and field names follow the Routes API computeRouteMatrix and Places API (New)
searchText references. Verify TWO_WHEELER and TRANSIT behaviour for Hyderabad with a live key.
"""

import math
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

import httpx

ROUTES_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
IST = timezone(timedelta(hours=5, minutes=30))

TRAVEL_MODES = {"car": "DRIVE", "bike": "TWO_WHEELER", "public": "TRANSIT", "any": "DRIVE"}
DAYPART = "weekday_0900"


class MapsError(Exception):
    """Maps could not give a trustworthy answer. Callers must not guess a value."""


class AddressNotFound(Exception):
    pass


@dataclass(frozen=True)
class LatLng:
    lat: float
    lng: float


def peak_departure(now: datetime | None = None) -> datetime:
    """The next weekday 9:00 am Hyderabad time, which is always in the future."""
    now = (now or datetime.now(UTC)).astimezone(IST)
    day = now.replace(hour=9, minute=0, second=0, microsecond=0)
    if day <= now:
        day += timedelta(days=1)
    while day.weekday() >= 5:  # skip Saturday and Sunday
        day += timedelta(days=1)
    return day


def _waypoint(p: LatLng) -> dict:
    return {"waypoint": {"location": {"latLng": {"latitude": p.lat, "longitude": p.lng}}}}


class RoutesClient:
    def __init__(self, api_key: str | None = None, http: httpx.Client | None = None):
        self.api_key = api_key or os.environ.get("MAPS_API_KEY", "")
        self.http = http or httpx.Client(timeout=15)

    def commute_minutes(
        self, origins: dict[str, LatLng], office: LatLng, commute_mode: str, departure: datetime
    ) -> dict[str, int]:
        """Minutes from each origin to the office at the given departure time.

        Origins with no route are left out. Any request failure raises MapsError.
        """
        if not self.api_key:
            raise MapsError("MAPS_API_KEY is not set")
        keys = list(origins)
        travel_mode = TRAVEL_MODES.get(commute_mode, "DRIVE")
        body: dict = {
            "origins": [_waypoint(origins[k]) for k in keys],
            "destinations": [_waypoint(office)],
            "travelMode": travel_mode,
            "departureTime": departure.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if travel_mode == "DRIVE":
            body["routingPreference"] = "TRAFFIC_AWARE"
        try:
            res = self.http.post(
                ROUTES_URL,
                json=body,
                headers={
                    "X-Goog-Api-Key": self.api_key,
                    "X-Goog-FieldMask": "originIndex,destinationIndex,duration,condition",
                },
            )
            res.raise_for_status()
            elements = res.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise MapsError(f"Routes API request failed: {type(exc).__name__}") from exc

        out: dict[str, int] = {}
        for el in elements if isinstance(elements, list) else []:
            if el.get("condition") != "ROUTE_EXISTS":
                continue
            match = re.fullmatch(r"(\d+(?:\.\d+)?)s", str(el.get("duration", "")))
            idx = el.get("originIndex")
            if match and isinstance(idx, int) and 0 <= idx < len(keys):
                out[keys[idx]] = math.ceil(float(match.group(1)) / 60)
        return out


class PlacesClient:
    # Rough box around Hyderabad, used to keep results inside the city we support.
    LOW = LatLng(17.2, 78.2)
    HIGH = LatLng(17.7, 78.7)

    def __init__(self, api_key: str | None = None, http: httpx.Client | None = None):
        self.api_key = api_key or os.environ.get("MAPS_API_KEY", "")
        self.http = http or httpx.Client(timeout=10)

    def find_address(self, text: str) -> tuple[str, LatLng]:
        if not self.api_key:
            raise MapsError("MAPS_API_KEY is not set")
        body = {
            "textQuery": text,
            "regionCode": "IN",
            "locationRestriction": {
                "rectangle": {
                    "low": {"latitude": self.LOW.lat, "longitude": self.LOW.lng},
                    "high": {"latitude": self.HIGH.lat, "longitude": self.HIGH.lng},
                }
            },
        }
        try:
            res = self.http.post(
                PLACES_URL,
                json=body,
                headers={
                    "X-Goog-Api-Key": self.api_key,
                    "X-Goog-FieldMask": "places.formattedAddress,places.location",
                },
            )
            res.raise_for_status()
            places = res.json().get("places") or []
        except (httpx.HTTPError, ValueError) as exc:
            raise MapsError(f"Places API request failed: {type(exc).__name__}") from exc
        if not places:
            raise AddressNotFound(text)
        top = places[0]
        loc = top["location"]
        return top["formattedAddress"], LatLng(loc["latitude"], loc["longitude"])


def in_hyderabad(lat: float, lng: float) -> bool:
    return (
        PlacesClient.LOW.lat <= lat <= PlacesClient.HIGH.lat
        and PlacesClient.LOW.lng <= lng <= PlacesClient.HIGH.lng
    )
