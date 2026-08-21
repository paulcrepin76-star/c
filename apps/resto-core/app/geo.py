from __future__ import annotations

import math
from decimal import Decimal

from app.config import settings

# Survey Cafe, Bonita Springs. Drive miles for local vendors are set on the supplier.
HOME_MARKET = "Bonita Springs, Florida"
NEAR_MILES = Decimal("15")
MID_MILES = Decimal("30")
FAR_MILES = Decimal("50")
FALLBACK_MILES = Decimal("250")
MILES_PER_KM = Decimal("0.621371")


def home_lat() -> float:
    return float(settings.home_lat)


def home_lon() -> float:
    return float(settings.home_lon)


def miles_between(lat1: float, lon1: float, lat2: float, lon2: float) -> Decimal:
    r_miles = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return Decimal(str(round(2 * r_miles * math.asin(math.sqrt(a)), 1)))


def miles_from_home(lat: float, lon: float) -> Decimal:
    return miles_between(home_lat(), home_lon(), lat, lon)


def km_for_miles(miles) -> float:
    return float(Decimal(str(miles)) / MILES_PER_KM)


def radius_band(miles) -> str:
    distance = Decimal(str(miles or 0))
    if distance <= 0:
        return "delivered"
    if distance <= NEAR_MILES:
        return "near"
    if distance <= MID_MILES:
        return "mid"
    if distance <= FAR_MILES:
        return "far"
    return "outside"


LOCAL_SUPPLIERS = {
    "Chef's Warehouse": {"city": "delivered", "miles": Decimal("0")},
    "Gordon Food Service": {"city": "delivered", "miles": Decimal("0")},
    "Costco": {"city": "Estero", "miles": Decimal("11")},
    "Sam's Club": {"city": "Fort Myers", "miles": Decimal("16")},
    "Restaurant Depot": {"city": "Fort Myers", "miles": Decimal("18")},
    "WebstaurantStore": {"city": "online", "miles": Decimal("0")},
}
