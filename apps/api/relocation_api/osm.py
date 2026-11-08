"""Free, keyless map provider: OSRM (commute) and Nominatim (address check), both OpenStreetMap.

Used when no MAPS_API_KEY is set and demo mode is off. Trade-off: OSRM has no live or
time-of-day traffic, so a peak-hour allowance is applied to road-network times and the screen
says so. Public servers have fair-use limits (Nominatim: 1 request per second, identify yourself
with a User-Agent). For heavy traffic, self-host both or switch to a paid provider.
"""

import math
import os
from datetime import datetime

import httpx

from relocation_api.maps import AddressNotFound, LatLng, MapsError, PlacesClient

OSRM_URL = os.environ.get("OSRM_URL", "https://router.project-osrm.org")
NOMINATIM_URL = os.environ.get("NOMINATIM_URL", "https://nominatim.openstreetmap.org")
USER_AGENT = os.environ.get("OSM_USER_AGENT", "TheNewGuyInTheTown/0.1 (relocation advisor)")

OSM_DAYPART = "osm_peak_estimate"  # keeps these out of the Google commute cache
OSM_BASIS = (
    "Road-network time with a peak-hour allowance, not live traffic. Map data from OpenStreetMap"
)
# OSRM's public server only routes for cars, so other modes are scaled from the car time.
PEAK_FACTOR = {"car": 1.6, "any": 1.6, "bike": 1.4, "public": 2.0}


class OsmRoutes:
    daypart = OSM_DAYPART

    def __init__(self, http: httpx.Client | None = None):
        self.http = http or httpx.Client(timeout=20, headers={"User-Agent": USER_AGENT})

    def commute_minutes(
        self, origins: dict[str, LatLng], office: LatLng, commute_mode: str, departure: datetime
    ) -> dict[str, int]:
        if not origins:
            return {}
        keys = list(origins)
        coords = [origins[k] for k in keys] + [office]
        path = ";".join(f"{p.lng},{p.lat}" for p in coords)
        sources = ";".join(str(i) for i in range(len(keys)))
        try:
            res = self.http.get(
                f"{OSRM_URL}/table/v1/driving/{path}",
                params={
                    "sources": sources,
                    "destinations": str(len(keys)),
                    "annotations": "duration",
                },
            )
            res.raise_for_status()
            data = res.json()
            rows = data["durations"] if data.get("code") == "Ok" else None
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise MapsError(f"OSRM request failed: {type(exc).__name__}") from exc
        if rows is None:
            raise MapsError("OSRM returned no durations")
        factor = PEAK_FACTOR.get(commute_mode, PEAK_FACTOR["any"])
        out: dict[str, int] = {}
        for key, row in zip(keys, rows, strict=False):
            seconds = row[0] if row else None
            if isinstance(seconds, int | float):
                out[key] = math.ceil(seconds * factor / 60)
        return out


class OsmPlaces:
    def __init__(self, http: httpx.Client | None = None):
        self.http = http or httpx.Client(timeout=10, headers={"User-Agent": USER_AGENT})

    def find_address(self, text: str) -> tuple[str, LatLng]:
        low, high = PlacesClient.LOW, PlacesClient.HIGH
        try:
            res = self.http.get(
                f"{NOMINATIM_URL}/search",
                params={
                    "q": text,
                    "format": "jsonv2",
                    "countrycodes": "in",
                    "viewbox": f"{low.lng},{high.lat},{high.lng},{low.lat}",
                    "bounded": 1,
                    "limit": 1,
                },
            )
            res.raise_for_status()
            hits = res.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise MapsError(f"Nominatim request failed: {type(exc).__name__}") from exc
        if not hits:
            raise AddressNotFound(text)
        top = hits[0]
        return top["display_name"], LatLng(float(top["lat"]), float(top["lon"]))
