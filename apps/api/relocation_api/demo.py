"""Demo mode: a way to run the whole product with no Google keys, clearly labelled as a demo.

Everything here is OFF unless DEMO_MODE=true, and the Maps parts apply only while MAPS_API_KEY
is empty. Real keys always win. Nothing here is used in staging or production.

- A demo sign-in for one fixed demo user.
- A short list of well-known Hyderabad offices, so an address can be "found" without Places.
- Commute times ESTIMATED from straight-line distance. They are not Google Maps numbers, and
  every screen that shows them says so.
"""

import math
import os
from datetime import datetime

from relocation_api.maps import AddressNotFound, LatLng

DEMO_USER_SUB = "demo-user"
DEMO_USER_EMAIL = "demo@example.com"
DEMO_DAYPART = "demo_estimate"  # keeps estimates out of the real commute cache
DEMO_BASIS = "Estimated from straight-line distance for peak hour. Demo data, not live Google Maps"

# name -> (display address, latitude, longitude). Approximate public landmarks.
OFFICES = {
    "wipro circle": ("Wipro Circle, Gachibowli, Hyderabad", 17.4401, 78.3489),
    "cyber towers": ("Cyber Towers, HITEC City, Hyderabad", 17.4504, 78.3811),
    "mindspace": ("Raheja Mindspace, HITEC City, Hyderabad", 17.4435, 78.3772),
    "microsoft": ("Microsoft Campus, Gachibowli, Hyderabad", 17.4333, 78.3430),
    "financial district": ("Financial District, Nanakramguda, Hyderabad", 17.4150, 78.3400),
    "kondapur": ("Kondapur, Hyderabad", 17.4600, 78.3640),
    "madhapur": ("Madhapur, Hyderabad", 17.4486, 78.3908),
}
SPEED_KMH = {"car": 18, "bike": 22, "public": 15, "any": 18}  # rough peak-hour averages
FIXED_MINUTES = 5  # parking, walking, waiting


def demo_mode() -> bool:
    return os.environ.get("DEMO_MODE", "false").strip().lower() == "true"


def use_demo_maps() -> bool:
    """Demo estimates are used only in demo mode, and only when no real Maps key is set."""
    return demo_mode() and not os.environ.get("MAPS_API_KEY")


def km_between(a: LatLng, b: LatLng) -> float:
    r = 6371.0
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp, dl = p2 - p1, math.radians(b.lng - a.lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


class DemoPlaces:
    def find_address(self, text: str) -> tuple[str, LatLng]:
        wanted = text.lower()
        for key, (address, lat, lng) in OFFICES.items():
            if key in wanted:
                return address, LatLng(lat, lng)
        raise AddressNotFound(text)


class DemoRoutes:
    daypart = DEMO_DAYPART

    def commute_minutes(
        self, origins: dict[str, LatLng], office: LatLng, commute_mode: str, departure: datetime
    ) -> dict[str, int]:
        speed = SPEED_KMH.get(commute_mode, SPEED_KMH["any"])
        # Roads are longer than straight lines, so scale the distance up a little.
        return {
            key: math.ceil(km_between(point, office) * 1.35 / speed * 60 + FIXED_MINUTES)
            for key, point in origins.items()
        }
