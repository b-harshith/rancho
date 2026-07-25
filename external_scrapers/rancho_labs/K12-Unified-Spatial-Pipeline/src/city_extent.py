"""Resolve city geographic bounding box via ArcGIS geocoding."""

from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
from dataclasses import dataclass

ssl._create_default_https_context = ssl._create_unverified_context

# Default buffer (~25 km) when ArcGIS does not return an extent
DEFAULT_BUFFER_DEG = 0.25
# Minimum bbox half-width; ArcGIS often returns a point-level extent for cities
MIN_HALF_WIDTH_DEG = 0.25


@dataclass
class CityExtent:
    city: str
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float
    centroid_lat: float
    centroid_lon: float

    @property
    def bbox_str(self) -> str:
        """Overture CLI format: min_lon,min_lat,max_lon,max_lat"""
        return f"{self.min_lon},{self.min_lat},{self.max_lon},{self.max_lat}"

    def __str__(self) -> str:
        return (
            f"{self.city}: bbox=[{self.min_lon:.4f},{self.min_lat:.4f},"
            f"{self.max_lon:.4f},{self.max_lat:.4f}] "
            f"centroid=({self.centroid_lat:.4f},{self.centroid_lon:.4f})"
        )


def _query_arcgis_city(city: str) -> dict | None:
    for query in (f"{city}, India", city):
        url = (
            "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/"
            "findAddressCandidates?"
            + urllib.parse.urlencode({"f": "json", "singleLine": query, "maxLocations": 1})
        )
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
        candidates = data.get("candidates") or []
        if candidates:
            return candidates[0]
    return None


def _ensure_min_extent(
    min_lon: float, min_lat: float, max_lon: float, max_lat: float,
    centroid_lon: float, centroid_lat: float,
    min_half_width: float = MIN_HALF_WIDTH_DEG,
) -> tuple[float, float, float, float]:
    """Expand bbox if ArcGIS returned a point-level extent too small for a city."""
    half_lon = (max_lon - min_lon) / 2
    half_lat = (max_lat - min_lat) / 2
    if half_lon >= min_half_width and half_lat >= min_half_width:
        return min_lon, min_lat, max_lon, max_lat
    return (
        centroid_lon - min_half_width,
        centroid_lat - min_half_width,
        centroid_lon + min_half_width,
        centroid_lat + min_half_width,
    )


def resolve_city_extent(city: str, buffer_deg: float = DEFAULT_BUFFER_DEG) -> CityExtent:
    """
    Geocode a city name via ArcGIS and extract its bounding box.

    Falls back to a buffer around the centroid when extent is unavailable.
    """
    candidate = _query_arcgis_city(city)
    if not candidate:
        raise ValueError(f"Could not geocode city: {city!r}")

    loc = candidate["location"]
    centroid_lon = float(loc["x"])
    centroid_lat = float(loc["y"])

    extent = candidate.get("extent")
    if extent and all(k in extent for k in ("xmin", "ymin", "xmax", "ymax")):
        min_lon = float(extent["xmin"])
        min_lat = float(extent["ymin"])
        max_lon = float(extent["xmax"])
        max_lat = float(extent["ymax"])
        min_lon, min_lat, max_lon, max_lat = _ensure_min_extent(
            min_lon, min_lat, max_lon, max_lat, centroid_lon, centroid_lat, buffer_deg
        )
    else:
        min_lon = centroid_lon - buffer_deg
        min_lat = centroid_lat - buffer_deg
        max_lon = centroid_lon + buffer_deg
        max_lat = centroid_lat + buffer_deg

    return CityExtent(
        city=city,
        min_lon=min_lon,
        min_lat=min_lat,
        max_lon=max_lon,
        max_lat=max_lat,
        centroid_lat=centroid_lat,
        centroid_lon=centroid_lon,
    )
