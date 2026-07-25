"""Shared evidence-only market analysis for live drive-time catchments.

This module deliberately keeps school enrollment attached to canonical campuses
and residential evidence attached to canonical societies.  It never allocates a
student to a home, hex, or centre.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import requests
from shapely.geometry import Point, mapping, shape


SCHEMA_VERSION = "2.0"
SUPPORTED_DURATIONS = (15, 30, 45, 60)
DEFAULT_FEE_SENSITIVITY = (175000, 180000, 200000)
DEFAULT_CAPTURE_RATES = (0.05, 0.10, 0.20)
Q4_TIERS = (
    ("Q4-Sub-Q1", "Premium Elite"),
    ("Q4-Sub-Q2", "Elite Luxury"),
    ("Q4-Sub-Q3", "Super Luxury"),
    ("Q4-Sub-Q4", "Ultra Luxury"),
)
RESIDENTIAL_TIERS = ("Luxury", "Super Luxury", "Ultra Luxury")
CATEGORY_BUCKETS = {
    "super_premium": frozenset({"super-premium"}),
    "premium": frozenset({"premium"}),
    "affordable": frozenset({"affordable"}),
    "budget": frozenset({"budget"}),
    "premium_plus": frozenset({"super-premium", "premium"}),
    "affordable_plus": frozenset({"super-premium", "premium", "affordable"}),
    "all_private": frozenset({"super-premium", "premium", "affordable", "budget"}),
}

SUPPORTED_CITY_IDS = ("delhi_ncr", "bengaluru", "hyderabad", "mumbai")
CITY_CENTERS = {
    "delhi_ncr": (28.6139, 77.2090),
    "bengaluru": (12.9716, 77.5946),
    "hyderabad": (17.3850, 78.4867),
    "mumbai": (19.0760, 72.8777),
}
CITY_COORDINATE_WINDOWS = {
    "delhi_ncr": (27.0, 76.0, 29.9, 78.8),
    "bengaluru": (12.0, 76.7, 14.1, 78.5),
    "hyderabad": (16.5, 77.5, 18.5, 79.6),
    "mumbai": (18.6, 72.6, 19.9, 73.7),
}
_GOOGLE_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{20,200}$")

_CENTRAL_LAT = 12.9716
_CENTRAL_LON = 77.5946
_DIRECTIONAL_ZONES = (
    "North", "North-East", "East", "South-East",
    "South", "South-West", "West", "North-West",
)


class CatchmentValidationError(ValueError):
    status_code = 400
    code = "invalid_request"


class CatchmentProviderError(RuntimeError):
    status_code = 502
    code = "isochrone_unavailable"


class CatchmentConfigurationError(RuntimeError):
    status_code = 503
    code = "provider_not_configured"


def error_payload(exc):
    return {
        "status": "error",
        "schema_version": SCHEMA_VERSION,
        "message": str(exc),
        "error": {"code": getattr(exc, "code", "internal_error"), "message": str(exc)},
    }


def validate_google_maps_api_key(value):
    """Validate an API key without retaining or echoing it."""
    if value is None:
        return None
    key = str(value).strip()
    if not key or not _GOOGLE_KEY_PATTERN.fullmatch(key):
        raise CatchmentValidationError("X-Google-Maps-Api-Key is malformed")
    return key


def google_maps_api_key(client_key=None):
    key = validate_google_maps_api_key(client_key)
    if key:
        return key
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if not key:
        raise CatchmentConfigurationError("GOOGLE_MAPS_API_KEY is not configured")
    try:
        return validate_google_maps_api_key(key)
    except CatchmentValidationError as exc:
        raise CatchmentConfigurationError("GOOGLE_MAPS_API_KEY is malformed") from exc


def _parse_isochrone_geometry(payload):
    if not isinstance(payload, dict):
        return None
    iso = payload.get("isochrone")
    if isinstance(iso, dict):
        for key in ("geoJson", "geojson", "geometry"):
            if iso.get(key):
                return iso[key]
    for key in ("geometry", "polygon", "boundary"):
        if payload.get(key):
            return payload[key]
    return None


_GEOMETRY_CACHE = {}
_GEOMETRY_CACHE_LOCK = threading.Lock()
_GEOMETRY_CACHE_TTL_SECONDS = 300


def clear_geometry_cache():
    with _GEOMETRY_CACHE_LOCK:
        _GEOMETRY_CACHE.clear()


def get_live_drive_isochrone(
    lat, lon, duration_mins, *, smooth_edges=True, now=None, api_key=None, strict=False
):
    """Return normalized GeoJSON and cache metadata for a live DRIVE isochrone."""
    duration_mins = validate_duration(duration_mins)
    now = time.time() if now is None else float(now)
    client_supplied = api_key is not None
    strict = bool(strict or client_supplied)
    # Client keys are request-scoped and must never be retained, even as part
    # of an in-memory cache key. They therefore bypass the shared cache.
    use_cache = not client_supplied
    cache_key = (round(float(lat), 6), round(float(lon), 6), duration_mins, bool(smooth_edges))
    if use_cache:
        with _GEOMETRY_CACHE_LOCK:
            cached = _GEOMETRY_CACHE.get(cache_key)
            if cached and now - cached[0] < _GEOMETRY_CACHE_TTL_SECONDS:
                return cached[1], {
                    "hit": True,
                    "age_seconds": round(now - cached[0], 3),
                    "provider": cached[2] if len(cached) > 2 else "unknown",
                }

    payload = {
        "location": {"latitude": float(lat), "longitude": float(lon)},
        "travel_duration": f"{duration_mins * 60}s",
        "travel_mode": "DRIVE",
        "routing_preference": "TRAFFIC_AWARE",
        "enable_smoothing": bool(smooth_edges),
        "travel_direction": "FROM",
    }
    try:
        response = requests.post(
            "https://isochrones.googleapis.com/v1/isochrones:generate",
            json=payload,
            headers={"Content-Type": "application/json", "X-Goog-Api-Key": google_maps_api_key(api_key)},
            timeout=45,
        )
        response.raise_for_status()
        raw_geometry = _parse_isochrone_geometry(response.json())
        if not raw_geometry:
            raise CatchmentProviderError("Google returned no usable isochrone geometry")
        normalized = shape(raw_geometry).buffer(0)
        if normalized.is_empty or normalized.geom_type not in {"Polygon", "MultiPolygon"}:
            raise CatchmentProviderError("Google returned an invalid isochrone geometry")
        geometry = mapping(normalized)
        provider = "google_isochrone"
    except CatchmentValidationError:
        raise
    except Exception as exc:
        if strict:
            raise CatchmentProviderError("Google live isochrone request failed") from exc
        radius_km = 20.0 * duration_mins / 60.0
        deg_lat = radius_km / 111.32
        deg_lon = radius_km / 108.4
        coords = []
        for i in range(32):
            angle = math.radians(i * 360.0 / 32.0)
            dx = deg_lon * math.cos(angle)
            dy = deg_lat * math.sin(angle)
            coords.append((float(lon) + dx, float(lat) + dy))
        coords.append(coords[0])
        from shapely.geometry import Polygon as ShapelyPolygon
        poly = ShapelyPolygon(coords)
        geometry = mapping(poly)
        provider = "circular_travel_speed_proxy"

    if use_cache:
        with _GEOMETRY_CACHE_LOCK:
            _GEOMETRY_CACHE[cache_key] = (now, geometry, provider)
    return geometry, {"hit": False, "age_seconds": 0.0, "provider": provider}


def validate_duration(value):
    try:
        duration = int(value)
    except (TypeError, ValueError) as exc:
        raise CatchmentValidationError("travel_time_mins must be one of 15, 30, 45, or 60") from exc
    if duration not in SUPPORTED_DURATIONS:
        raise CatchmentValidationError("travel_time_mins must be one of 15, 30, 45, or 60")
    return duration


def _parse_csv_numbers(raw, *, name, defaults, maximum_items=10, integer=False):
    if raw is None or str(raw).strip() == "":
        return list(defaults)
    values = []
    for part in str(raw).split(","):
        try:
            value = int(part) if integer else float(part)
        except (TypeError, ValueError) as exc:
            raise CatchmentValidationError(f"{name} contains an invalid number") from exc
        if value <= 0:
            raise CatchmentValidationError(f"{name} values must be positive")
        values.append(value)
    values = sorted(set(values))
    if len(values) > maximum_items:
        raise CatchmentValidationError(f"{name} accepts at most {maximum_items} values")
    return values


def parse_market_options(params):
    thresholds = _parse_csv_numbers(
        (params.get("fee_sensitivity_thresholds") or [None])[0],
        name="fee_sensitivity_thresholds",
        defaults=DEFAULT_FEE_SENSITIVITY,
        integer=True,
    )
    capture_rates = _parse_csv_numbers(
        (params.get("capture_rates") or [None])[0],
        name="capture_rates",
        defaults=DEFAULT_CAPTURE_RATES,
    )
    if any(rate > 1 for rate in capture_rates):
        raise CatchmentValidationError("capture_rates must be decimals in (0, 1]")
    try:
        capacity = int((params.get("center_capacity") or [200])[0])
        utilization = float((params.get("target_utilization") or [0.8])[0])
    except (TypeError, ValueError) as exc:
        raise CatchmentValidationError("center_capacity and target_utilization must be numeric") from exc
    if capacity <= 0:
        raise CatchmentValidationError("center_capacity must be positive")
    if not 0 < utilization <= 1:
        raise CatchmentValidationError("target_utilization must be in (0, 1]")
    return {
        "fee_sensitivity_thresholds": thresholds,
        "capture_rates": capture_rates,
        "center_capacity": capacity,
        "target_utilization": utilization,
    }


def parse_market_options_payload(payload):
    payload = payload or {}
    params = {}
    for key in ("fee_sensitivity_thresholds", "capture_rates"):
        if key in payload:
            value = payload[key]
            params[key] = [",".join(str(item) for item in value) if isinstance(value, list) else str(value)]
    for key in ("center_capacity", "target_utilization"):
        if key in payload:
            params[key] = [str(payload[key])]
    return parse_market_options(params)


def validate_live_request(*, lat, lon, catchment_mode, travel_mode, live_traffic, duration):
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError) as exc:
        raise CatchmentValidationError("lat and lon must be numeric") from exc
    if not -90 <= lat <= 90 or not -180 <= lon <= 180 or (lat == 0 and lon == 0):
        raise CatchmentValidationError("lat or lon is outside its valid range")
    if str(catchment_mode).lower() != "time":
        raise CatchmentValidationError("catchment_mode must be time; distance fallback is not supported")
    if str(travel_mode).upper() != "DRIVE":
        raise CatchmentValidationError("travel_mode must be DRIVE")
    if str(live_traffic).lower() != "true":
        raise CatchmentValidationError("live_traffic must be true")
    return lat, lon, validate_duration(duration)


def validate_catchment_city(value):
    city_id = str(value or "").strip()
    if city_id not in SUPPORTED_CITY_IDS:
        raise CatchmentValidationError("city must be one of delhi_ncr, bengaluru, hyderabad, or mumbai")
    return city_id


def validate_city_coordinates(city_id, lat, lon):
    city_id = validate_catchment_city(city_id)
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError) as exc:
        raise CatchmentValidationError("lat and lon must be numeric") from exc
    south, west, north, east = CITY_COORDINATE_WINDOWS[city_id]
    if not (south <= lat <= north and west <= lon <= east):
        raise CatchmentValidationError("lat and lon are outside the selected city")
    return lat, lon


def _haversine_km(lat1, lon1, lat2, lon2):
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def classify_zone(lat, lon, city_id=None):
    center_lat, center_lon = CITY_CENTERS.get(city_id, (_CENTRAL_LAT, _CENTRAL_LON))
    if _haversine_km(center_lat, center_lon, lat, lon) <= 5.0:
        return "Central"
    p1, p2 = math.radians(center_lat), math.radians(lat)
    dl = math.radians(lon - center_lon)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    bearing = (math.degrees(math.atan2(x, y)) + 360) % 360
    index = int(((bearing + 22.5) % 360) // 45)
    return _DIRECTIONAL_ZONES[index]


def allowed_zones(origin_zone):
    if origin_zone == "Central":
        return ["Central", *_DIRECTIONAL_ZONES]
    if origin_zone not in _DIRECTIONAL_ZONES:
        return [origin_zone]
    idx = _DIRECTIONAL_ZONES.index(origin_zone)
    return [origin_zone, "Central", _DIRECTIONAL_ZONES[(idx - 1) % 8], _DIRECTIONAL_ZONES[(idx + 1) % 8]]


def _number(row, *keys, default=None):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return default


def _stable_id(prefix, row, *preferred):
    for key in preferred:
        value = row.get(key)
        if value:
            return f"{prefix}_{value}"
    raw = "|".join([
        str(row.get("name", "")).strip().lower(),
        f"{_number(row, 'lat', default=0):.6f}",
        f"{_number(row, 'lon', 'lng', default=0):.6f}",
    ])
    return f"{prefix}_{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]}"


def _normalize_boards(value):
    if isinstance(value, list):
        parts = value
    else:
        parts = re.split(r"[/,|]", str(value or ""))
    aliases = {"IGCSE": "Cambridge/IGCSE", "CAMBRIDGE": "Cambridge/IGCSE", "ISC": "ICSE/ISC", "ICSE": "ICSE/ISC"}
    result = []
    for part in parts:
        item = str(part).strip()
        if not item:
            continue
        item = aliases.get(item.upper(), item)
        if item not in result:
            result.append(item)
    return result or ["Other"]


def _school_rows(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("campuses", "schools", "entities", "data"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


def _canonicalize_schools(rows, city_id=None):
    grouped = {}
    for row in rows:
        lat = _number(row, "lat", "latitude")
        lon = _number(row, "lon", "lng", "longitude")
        if lat is None or lon is None:
            continue
        campus_id = str(row.get("campus_id") or row.get("canonical_campus_id") or _stable_id("campus", row, "google_place_id", "udise_code"))
        entity_id = str(row.get("entity_id") or row.get("school_entity_id") or _stable_id("entity", row, "udise_code", "google_place_id"))
        enrollment_by_source = row.get("enrollment_by_source") or {}
        enrollment_source = row.get("enrollment_source")
        if not enrollment_source:
            enrollment_source = "udise" if float(enrollment_by_source.get("udise_backed", 0) or 0) > 0 else "estimated"
        candidate = {
            "entity_id": entity_id,
            "campus_id": campus_id,
            "name": row.get("name") or row.get("school_name") or "Unnamed school",
            "lat": lat,
            "lon": lon,
            "zone": row.get("zone") or classify_zone(lat, lon, city_id),
            "fee_min_inr": _number(row, "fee_min_inr", "fee_min", "fee"),
            "fee_max_inr": _number(row, "fee_max_inr", "fee_max", "fee_min", "fee"),
            "fee_bucket": str(row.get("fee_bucket") or row.get("fee_tier") or "").strip().lower().replace("_", "-"),
            "fee_quartile": row.get("fee_quartile") or row.get("quartile") or row.get("quartile analysis 1"),
            "q4_subquartile": row.get("q4_subquartile") or row.get("quartile analysis 2"),
            "q4_tier_label": row.get("q4_tier_label") or row.get("q4_segment") or row.get("quartile_category"),
            "boards": _normalize_boards(row.get("boards") or row.get("board")),
            "grade_2_9_enrollment": _number(row, "grade_2_9_enrollment", "students_grades_2_9", "students", default=0) or 0,
            "enrollment_source": str(enrollment_source or "unknown").lower(),
            "udise_codes": [str(v) for v in (row.get("udise_codes") or ([row.get("udise_code")] if row.get("udise_code") else []))],
            "source_row_ids": list(row.get("source_row_ids") or row.get("entity_ids") or row.get("source_row_indexes") or []),
        }
        existing = grouped.get(entity_id)
        if not existing:
            grouped[entity_id] = candidate
            continue
        # Fallback merging is only used when no canonical entity artifact exists.
        existing["grade_2_9_enrollment"] = max(existing["grade_2_9_enrollment"], candidate["grade_2_9_enrollment"])
        fee_mins = [v for v in (existing["fee_min_inr"], candidate["fee_min_inr"]) if v is not None]
        fee_maxes = [v for v in (existing["fee_max_inr"], candidate["fee_max_inr"]) if v is not None]
        existing["fee_min_inr"] = min(fee_mins) if fee_mins else None
        existing["fee_max_inr"] = max(fee_maxes) if fee_maxes else None
        existing["boards"] = sorted(set(existing["boards"] + candidate["boards"]))
        existing["udise_codes"] = sorted(set(existing["udise_codes"] + candidate["udise_codes"]))
        if candidate["fee_quartile"] == "Q4":
            existing.update({k: candidate[k] for k in ("fee_quartile", "q4_subquartile", "q4_tier_label")})
    return list(grouped.values())


def load_market_data(data_dir, city_id=None):
    data_dir = Path(data_dir)
    if city_id is not None:
        city_id = validate_catchment_city(city_id)
    # The canonical entity artifact is the only permitted school-market input.
    # Falling back to legacy/raw campus files can silently restore an obsolete
    # school universe and invalidate Q4 membership.
    school_path = data_dir / "school_entities.json"
    if not school_path.exists():
        raise FileNotFoundError(f"Canonical school market is missing: {school_path}")
    schools = []
    school_revision = "missing"
    payload = json.loads(school_path.read_text(encoding="utf-8"))
    schools = _canonicalize_schools(_school_rows(payload), city_id)
    school_revision = hashlib.sha1(school_path.read_bytes()).hexdigest()[:12]

    society_path = data_dir / "societies.json"
    societies = []
    society_revision = "missing"
    if society_path.exists():
        payload = json.loads(society_path.read_text(encoding="utf-8"))
        rows = payload if isinstance(payload, list) else payload.get("societies", [])
        seen = set()
        for row in rows:
            lat = _number(row, "lat", "latitude")
            lon = _number(row, "lon", "lng", "longitude")
            if lat is None or lon is None:
                continue
            society_id = str(row.get("society_id") or row.get("canonical_society_id") or _stable_id("society", row))
            if society_id in seen:
                continue
            seen.add(society_id)
            societies.append({
                "society_id": society_id,
                "name": row.get("name") or "Unnamed society",
                "lat": lat,
                "lon": lon,
                "zone": row.get("zone") or classify_zone(lat, lon, city_id),
                "tier": row.get("category"),
                "family_proxy": _number(row, "tam", "family_proxy", default=0) or 0,
                "units": _number(row, "units", default=0) or 0,
            })
        society_revision = hashlib.sha1(society_path.read_bytes()).hexdigest()[:12]
    return {
        "schools": schools,
        "societies": societies,
        "data_revision": f"schools-{school_revision}.societies-{society_revision}",
        "school_source": school_path.name,
        "city_id": city_id,
    }


def _aggregate_schools(rows):
    source = defaultdict(lambda: {"entity_count": 0, "campus_count": 0, "enrollment": 0.0})
    boards = defaultdict(lambda: {"entity_count": 0, "campus_count": 0, "enrollment": 0.0})
    tiers = {key: {"label": label, "entity_count": 0, "campus_count": 0, "enrollment": 0.0} for key, label in Q4_TIERS}
    total = 0.0
    source_campuses = defaultdict(set)
    board_campuses = defaultdict(set)
    tier_campuses = defaultdict(set)
    for row in rows:
        enrollment = row["grade_2_9_enrollment"]
        total += enrollment
        src = row["enrollment_source"]
        source[src]["entity_count"] += 1
        source_campuses[src].add(row["campus_id"])
        source[src]["enrollment"] += enrollment
        for board in row["boards"]:
            boards[board]["entity_count"] += 1
            board_campuses[board].add(row["campus_id"])
            boards[board]["enrollment"] += enrollment
        sub = row.get("q4_subquartile")
        if sub in tiers:
            tiers[sub]["entity_count"] += 1
            tier_campuses[sub].add(row["campus_id"])
            tiers[sub]["enrollment"] += enrollment
    for key, campuses in source_campuses.items():
        source[key]["campus_count"] = len(campuses)
    for key, campuses in board_campuses.items():
        boards[key]["campus_count"] = len(campuses)
    for key, campuses in tier_campuses.items():
        tiers[key]["campus_count"] = len(campuses)
    def rounded(mapping_value):
        return {key: {**value, "enrollment": round(value["enrollment"], 2)} for key, value in mapping_value.items()}
    return {
        "entity_count": len(rows),
        "campus_count": len({row["campus_id"] for row in rows}),
        "grade_2_9_enrollment": round(total, 2),
        "source_composition": rounded(source),
        "by_board": rounded(boards),
        "by_q4_subquartile": rounded(tiers),
    }


def capacity_scenarios(enrollment, capture_rates, capacity, target_utilization):
    results = []
    for rate in capture_rates:
        captured = float(enrollment) * rate
        minimum_required = math.ceil(captured / capacity) if captured else 0
        maximum_at_target = math.floor(captured / (capacity * target_utilization)) if captured else 0
        utilization = captured / (minimum_required * capacity) if minimum_required else 0.0
        packed_full = math.floor(captured / capacity)
        results.append({
            "capture_rate": rate,
            "captured_students": round(captured, 2),
            "packed_full_centers": packed_full,
            "packed_residual_students": round(captured - packed_full * capacity, 2),
            "minimum_centers_required": minimum_required,
            "maximum_centers_at_target_utilization": maximum_at_target,
            "utilization_at_minimum_centers": round(utilization, 6),
            "below_target_utilization": bool(minimum_required and utilization < target_utilization),
        })
    return results


def _public_entity(row, relation):
    result = dict(row)
    result["zone_relation"] = relation
    return result


def _campus_context(rows):
    campuses = {}
    for row in rows:
        campus = campuses.setdefault(row["campus_id"], {
            "campus_id": row["campus_id"],
            "name": row["name"],
            "lat": row["lat"],
            "lon": row["lon"],
            "zone": row["zone"],
            "zone_relation": row.get("zone_relation"),
            "entity_ids": [],
            "q4_entity_count": 0,
            "grade_2_9_enrollment": 0.0,
        })
        campus["entity_ids"].append(row["entity_id"])
        campus["q4_entity_count"] += 1
        campus["grade_2_9_enrollment"] += row["grade_2_9_enrollment"]
    for campus in campuses.values():
        campus["entity_ids"] = sorted(set(campus["entity_ids"]))
        campus["grade_2_9_enrollment"] = round(campus["grade_2_9_enrollment"], 2)
    return list(campuses.values())


def build_market_ledger(*, geometry, center_lat, center_lon, market_data, options):
    area = shape(geometry).buffer(0)
    origin_zone = classify_zone(
        float(center_lat), float(center_lon), market_data.get("city_id")
    )
    permitted = allowed_zones(origin_zone)
    permitted_set = set(permitted)

    inside = [row for row in market_data["schools"] if area.covers(Point(row["lon"], row["lat"]))]
    category_id = options.get("category")
    if category_id:
        allowed_buckets = CATEGORY_BUCKETS.get(category_id)
        if allowed_buckets is None:
            raise CatchmentValidationError(f"Unknown school category: {category_id}")
        selected_inside = [
            row for row in inside
            if row.get("fee_bucket") in allowed_buckets and row["grade_2_9_enrollment"] > 0
        ]
        cohort = {
            "id": category_id,
            "label": category_id.replace("_", " ").title(),
            "basis_field": "fee_tier",
            "category_id": category_id,
            "annual_fee_filter_supported": False,
        }
    else:
        selected_inside = [
            row for row in inside
            if row.get("fee_quartile") == "Q4" and row["grade_2_9_enrollment"] > 0
        ]
        cohort = {
            "id": "fee_max_q4",
            "label": "Q4 — top 25% by annual fee maximum",
            "basis_field": "fee_max_inr",
            "quartile": "Q4",
        }
    direct_rows = [row for row in selected_inside if row["zone"] == origin_zone]
    adjacent_rows = [row for row in selected_inside if row["zone"] in permitted_set and row["zone"] != origin_zone]
    reachable_rows = direct_rows + adjacent_rows
    excluded_rows = [row for row in selected_inside if row["zone"] not in permitted_set]

    threshold_items = []
    for threshold in options["fee_sensitivity_thresholds"]:
        eligible = [
            row for row in inside
            if row.get("fee_max_inr") is not None
            and row["fee_max_inr"] >= threshold
            and row["grade_2_9_enrollment"] > 0
        ]
        direct = [row for row in eligible if row["zone"] == origin_zone]
        adjacent = [row for row in eligible if row["zone"] in permitted_set and row["zone"] != origin_zone]
        reachable = direct + adjacent
        aggregate = _aggregate_schools(reachable)
        public_entities = [
            *[_public_entity(row, "direct") for row in direct],
            *[_public_entity(row, "adjacent") for row in adjacent],
        ]
        threshold_items.append({
            "threshold_inr": threshold,
            "cohort": {
                "id": f"fee_max_gte_{threshold}",
                "label": f"Annual fee maximum at or above INR {threshold}",
                "basis_field": "fee_max_inr",
                "operator": "gte",
                "threshold_inr": threshold,
            },
            "direct": _aggregate_schools(direct),
            "reachable": aggregate,
            "entities": public_entities,
            "campuses": _campus_context(public_entities),
            "capacity_scenarios": capacity_scenarios(
                aggregate["grade_2_9_enrollment"], options["capture_rates"],
                options["center_capacity"], options["target_utilization"],
            ),
        })

    inside_societies = [
        row for row in market_data["societies"]
        if row.get("tier") in RESIDENTIAL_TIERS and area.covers(Point(row["lon"], row["lat"]))
    ]
    society_by_tier = {}
    for tier in RESIDENTIAL_TIERS:
        rows = [row for row in inside_societies if row["tier"] == tier]
        society_by_tier[tier] = {
            "society_count": len(rows),
            "family_proxy": round(sum(row["family_proxy"] for row in rows), 2),
            "units": round(sum(row["units"] for row in rows), 2),
        }
    residential_summary = {
        "society_count": len(inside_societies),
        "family_proxy": round(sum(row["family_proxy"] for row in inside_societies), 2),
        "units": round(sum(row["units"] for row in inside_societies), 2),
    }

    reachable_aggregate = _aggregate_schools(reachable_rows)
    school_market = {
        "cohort": cohort,
        "direct": _aggregate_schools(direct_rows),
        "adjacent": _aggregate_schools(adjacent_rows),
        "reachable": reachable_aggregate,
        "excluded": {
            "non_adjacent_inside_isochrone": _aggregate_schools(excluded_rows),
            "missing_or_zero_enrollment_inside_isochrone": sum(
                1 for row in inside
                if (
                    row.get("fee_bucket") in CATEGORY_BUCKETS.get(category_id, frozenset())
                    if category_id else row.get("fee_quartile") == "Q4"
                ) and row["grade_2_9_enrollment"] <= 0
            ),
        },
        "entities": [
            *[_public_entity(row, "direct") for row in direct_rows],
            *[_public_entity(row, "adjacent") for row in adjacent_rows],
        ],
        "campuses": _campus_context([
            *[_public_entity(row, "direct") for row in direct_rows],
            *[_public_entity(row, "adjacent") for row in adjacent_rows],
        ]),
        "excluded_non_adjacent_entities": [_public_entity(row, "non_adjacent") for row in excluded_rows],
        "absolute_fee_sensitivity": {
            "basis": "maximum_annual_fee_inr",
            "relationship_to_primary": "alternate_cohort",
            "items": threshold_items,
        },
    }
    return {
        "geography": {
            "origin_zone": origin_zone,
            "allowed_zones": permitted,
            "adjacency_rule": "origin plus Central and two neighboring directional zones; Central allows all zones",
        },
        "school_market": school_market,
        "residential_market": {
            "included_tiers": list(RESIDENTIAL_TIERS),
            "methodology": "unique society points covered by the live isochrone; family_proxy is the sum of society tam only",
            "excluded_categories": "all categories other than Luxury, Super Luxury, and Ultra Luxury",
            "inside_isochrone": residential_summary,
            "by_tier": society_by_tier,
            "societies": inside_societies,
        },
        "capacity": {
            "basis": f"{category_id or 'q4'}_reachable_unique_grade_2_9_enrollment",
            "capacity_per_center": options["center_capacity"],
            "target_utilization": options["target_utilization"],
            "scenarios": capacity_scenarios(
                reachable_aggregate["grade_2_9_enrollment"], options["capture_rates"],
                options["center_capacity"], options["target_utilization"],
            ),
        },
    }


def build_portfolio_result(center_results, options, *, cohort=None, include_sensitivity=True):
    """Aggregate centre evidence without assigning an entity or student to a centre."""
    if not isinstance(center_results, list) or not center_results:
        raise CatchmentValidationError("center_results must contain at least one result")
    if len(center_results) > 10:
        raise CatchmentValidationError("portfolio accepts at most 10 centers")

    primary_cohorts = {
        str((result.get("school_market") or {}).get("cohort", {}).get("id"))
        for result in center_results
        if (result.get("school_market") or {}).get("cohort", {}).get("id")
    }
    if cohort is None and len(primary_cohorts) > 1:
        raise CatchmentValidationError("portfolio center results must use one consistent cohort")
    if cohort is None:
        cohort = (center_results[0].get("school_market") or {}).get("cohort") or {
            "id": "supplied_entity_cohort", "label": "Supplied reachable entity cohort"
        }

    normalized = []
    entity_touchpoints = defaultdict(list)
    campus_touchpoints = defaultdict(list)
    entity_records = {}
    for index, result in enumerate(center_results):
        center_id = str(result.get("center_id") or result.get("id") or f"center-{index + 1}")
        market = result.get("school_market") or {}
        entities = market.get("entities") or []
        entity_map = {}
        campus_ids = set()
        for entity in entities:
            entity_id = str(entity.get("entity_id") or "")
            campus_id = str(entity.get("campus_id") or "")
            if not entity_id or not campus_id:
                raise CatchmentValidationError("every portfolio entity requires entity_id and campus_id")
            # A malformed duplicate within one result is counted once.
            previous = entity_map.get(entity_id)
            if previous is None or float(entity.get("grade_2_9_enrollment", 0) or 0) > float(previous.get("grade_2_9_enrollment", 0) or 0):
                entity_map[entity_id] = entity
            campus_ids.add(campus_id)
        for entity_id, entity in entity_map.items():
            entity_touchpoints[entity_id].append(center_id)
            entity_records.setdefault(entity_id, entity)
        for campus_id in campus_ids:
            campus_touchpoints[campus_id].append(center_id)
        normalized.append({
            "center_id": center_id,
            "entity_map": entity_map,
            "entity_ids": set(entity_map),
            "campus_ids": campus_ids,
            "reachable_entity_count": len(entity_map),
            "reachable_campus_count": len(campus_ids),
            "reachable_grade_2_9_enrollment": round(sum(float(row.get("grade_2_9_enrollment", 0) or 0) for row in entity_map.values()), 2),
        })

    unique_entities = set(entity_records)
    unique_campuses = {str(row["campus_id"]) for row in entity_records.values()}
    unique_enrollment = round(sum(float(row.get("grade_2_9_enrollment", 0) or 0) for row in entity_records.values()), 2)
    pairwise = []
    for first, second in combinations(normalized, 2):
        shared_entities = first["entity_ids"] & second["entity_ids"]
        union_entities = first["entity_ids"] | second["entity_ids"]
        shared_campuses = first["campus_ids"] & second["campus_ids"]
        shared_enrollment = round(sum(float(entity_records[eid].get("grade_2_9_enrollment", 0) or 0) for eid in shared_entities), 2)
        pairwise.append({
            "center_a": first["center_id"],
            "center_b": second["center_id"],
            "shared_entity_count": len(shared_entities),
            "shared_campus_count": len(shared_campuses),
            "shared_grade_2_9_enrollment": shared_enrollment,
            "entity_jaccard": round(len(shared_entities) / len(union_entities), 6) if union_entities else 0.0,
            "pct_of_a_entities": round(len(shared_entities) / len(first["entity_ids"]), 6) if first["entity_ids"] else 0.0,
            "pct_of_b_entities": round(len(shared_entities) / len(second["entity_ids"]), 6) if second["entity_ids"] else 0.0,
        })

    seen_entities = set()
    seen_campuses = set()
    incremental = []
    for center in normalized:
        new_entities = center["entity_ids"] - seen_entities
        new_campuses = center["campus_ids"] - seen_campuses
        seen_entities.update(center["entity_ids"])
        seen_campuses.update(center["campus_ids"])
        incremental.append({
            "center_id": center["center_id"],
            "incremental_entity_count": len(new_entities),
            "incremental_campus_count": len(new_campuses),
            "incremental_grade_2_9_enrollment": round(sum(float(entity_records[eid].get("grade_2_9_enrollment", 0) or 0) for eid in new_entities), 2),
            "cumulative_unique_entity_count": len(seen_entities),
            "cumulative_unique_campus_count": len(seen_campuses),
        })

    result = {
        "methodology": "unique entity union with campus overlap context; no student is allocated to a center",
        "cohort": cohort,
        "cohort_consistent": True,
        "center_count": len(normalized),
        "centers": [{key: value for key, value in center.items() if not key.endswith("_ids") and key not in {"entity_map"}} for center in normalized],
        "unique_reachable_entity_count": len(unique_entities),
        "unique_reachable_campus_count": len(unique_campuses),
        "unique_reachable_grade_2_9_enrollment": unique_enrollment,
        "shared_entity_touchpoints": [
            {"entity_id": entity_id, "center_ids": center_ids, "grade_2_9_enrollment": entity_records[entity_id].get("grade_2_9_enrollment", 0)}
            for entity_id, center_ids in sorted(entity_touchpoints.items()) if len(center_ids) > 1
        ],
        "shared_campus_touchpoints": [
            {"campus_id": campus_id, "center_ids": center_ids}
            for campus_id, center_ids in sorted(campus_touchpoints.items()) if len(center_ids) > 1
        ],
        "pairwise_overlap": pairwise,
        "incremental_by_request_order": incremental,
        "capacity": {
            "basis": "portfolio_unique_reachable_entity_enrollment",
            "cohort_id": cohort.get("id") if isinstance(cohort, dict) else str(cohort),
            "capacity_per_center": options["center_capacity"],
            "target_utilization": options["target_utilization"],
            "scenarios": capacity_scenarios(
                unique_enrollment, options["capture_rates"],
                options["center_capacity"], options["target_utilization"],
            ),
        },
    }
    if include_sensitivity:
        threshold_sets = []
        for center_result in center_results:
            items = ((center_result.get("school_market") or {}).get("absolute_fee_sensitivity") or {}).get("items") or []
            threshold_sets.append({int(item["threshold_inr"]) for item in items})
        if threshold_sets and any(values != threshold_sets[0] for values in threshold_sets[1:]):
            raise CatchmentValidationError("portfolio center results must expose the same fee sensitivity thresholds")
        sensitivity_items = []
        for threshold in sorted(threshold_sets[0]) if threshold_sets else []:
            derived_results = []
            threshold_cohort = None
            for center_result in center_results:
                item = next(
                    item for item in center_result["school_market"]["absolute_fee_sensitivity"]["items"]
                    if int(item["threshold_inr"]) == threshold
                )
                threshold_cohort = threshold_cohort or item.get("cohort")
                derived_results.append({
                    "center_id": center_result.get("center_id") or center_result.get("id"),
                    "school_market": {"cohort": item.get("cohort"), "entities": item.get("entities") or []},
                })
            sensitivity_items.append({
                "threshold_inr": threshold,
                "cohort": threshold_cohort,
                "portfolio": build_portfolio_result(
                    derived_results, options, cohort=threshold_cohort, include_sensitivity=False
                ),
            })
        result["absolute_fee_sensitivity"] = {
            "basis": "maximum_annual_fee_inr",
            "relationship_to_primary": "alternate_cohort",
            "items": sensitivity_items,
        }
    return result
