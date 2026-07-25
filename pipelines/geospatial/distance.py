"""Straight-line distance helpers used for inexpensive spatial screening.

These functions intentionally replace routing-engine calls for high-volume,
multi-city candidate screening.  They do not estimate travel time or road
distance.
"""

from __future__ import annotations

from math import asin, cos, isfinite, radians, sin, sqrt

EARTH_RADIUS_KM = 6371.0088


def _coordinate(value: float, *, minimum: float, maximum: float, name: str) -> float:
    value = float(value)
    if not isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be finite and between {minimum} and {maximum}")
    return value


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return WGS84 great-circle distance in kilometres.

    The haversine formula is numerically stable for the short distances used
    by geocoding and entity-match screens.  The returned value is a geometric
    screening distance, not a route distance.
    """

    lat1 = _coordinate(lat1, minimum=-90, maximum=90, name="lat1")
    lon1 = _coordinate(lon1, minimum=-180, maximum=180, name="lon1")
    lat2 = _coordinate(lat2, minimum=-90, maximum=90, name="lat2")
    lon2 = _coordinate(lon2, minimum=-180, maximum=180, name="lon2")
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(min(1.0, a)))


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return WGS84 great-circle distance in metres."""

    return haversine_km(lat1, lon1, lat2, lon2) * 1000.0
