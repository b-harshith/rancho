from __future__ import annotations

from typing import Any

from .core import SafetyError, lineage

SOURCE_ENTITY_TYPE = {
    "yellowslate": "school",
    "udise": "school",
    "magicbricks": "project",
    "99acres": "locality",
    "practo": "hospital",
}


def _first(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value: Any = record
        for part in key.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if value not in (None, ""):
            return value
    return None


def extract_records(source: str, payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    candidates = {
        "yellowslate": ("schools", "data.schools", "records"),
        "magicbricks": ("resultList", "data", "projects", "records"),
        "99acres": ("data", "localities", "records", "result"),
        "practo": ("hospitals", "data.hospitals", "results", "records"),
        "udise": ("schools", "data", "records"),
    }[source]
    for path in candidates:
        value = _first(payload, path)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    return [payload] if isinstance(payload, dict) else []


def normalize(source: str, city: str, mapping: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    entity_type = SOURCE_ENTITY_TYPE[source]
    ids = {
        "yellowslate": ("id", "schoolId", "slug", "url"),
        "magicbricks": ("psmid", "projectId", "id"),
        "99acres": ("id", "locationId", "localityId"),
        "practo": ("hospital_id", "hospitalId", "id", "url"),
        "udise": ("udise_code", "udiseCode", "schoolId"),
    }[source]
    rid = _first(record, *ids)
    if rid is None:
        raise SafetyError("missing source record id")
    source_city_id = _first(record, "source_city_id", "cityId", "city_id") or mapping.get("city_id")
    source_city_name = _first(record, "source_city_name", "cityName", "ctname", "city") or mapping.get("city_name")
    source_url = _first(record, "source_url", "url", "projectUrl", "profileUrl")
    if not isinstance(source_url, str) or not source_url.startswith(("https://", "http://")):
        raise SafetyError("missing or invalid source URL")
    name = _first(record, "name", "schoolName", "projectName", "hospitalName", "label")
    if not name:
        raise SafetyError("missing name")
    try:
        base = lineage(city, entity_type, source, str(rid), source_city_id, source_city_name, source_url, record)
    except ValueError as exc:
        raise SafetyError(str(exc)) from exc
    base.update({
        "entity_kind": entity_type,
        "name": name,
        "lat": _first(record, "lat", "latitude", "location.lat"),
        "lon": _first(record, "lon", "lng", "longitude", "location.lng"),
        "coordinate_source": "source" if _first(record, "lat", "latitude", "location.lat") is not None else None,
        "coordinate_precision": None,
        "address": _first(record, "address", "fullAddress", "locality"),
    })
    if entity_type == "school":
        base.update({
            "udise_code": _first(record, "udise_code", "udiseCode"),
            "enrollment": _first(record, "enrollment", "studentCount"),
            "annual_fee_min": _first(record, "annual_fee_min", "feeMin"),
            "annual_fee_max": _first(record, "annual_fee_max", "feeMax"),
        })
    elif entity_type == "project":
        base.update({
            "developer": _first(record, "developer", "developerName"),
            "total_units": _first(record, "total_units", "totalUnits"),
            "price_min": _first(record, "price_min", "minPrice"),
            "price_max": _first(record, "price_max", "maxPrice"),
            "construction_status": _first(record, "construction_status", "status"),
        })
    elif entity_type == "locality":
        base.update({
            "price_per_sqft": _first(record, "price_per_sqft", "pricePerSqft"),
            "rating": _first(record, "rating"),
            "review_count": _first(record, "review_count", "reviewCount"),
        })
    elif entity_type == "hospital":
        base.update({
            "rating": _first(record, "rating"),
            "review_count": _first(record, "review_count", "reviewCount"),
            "bed_count": _first(record, "bed_count", "bedCount"),
        })
    return base
