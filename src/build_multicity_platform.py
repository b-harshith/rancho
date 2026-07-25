#!/usr/bin/env python3
"""Build deterministic, city-scoped artifacts for the Rancho expansion platform.

The pipeline intentionally uses the supplied fee_tier labels only.  The source
does not contain comparable annual fees, so it cannot support arbitrary fee
thresholds.  Raw source files are never modified.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    import h3
except ImportError as exc:  # pragma: no cover - dependency is present in repo runtime
    raise SystemExit("The 'h3' Python package is required to build spatial aggregates") from exc


SCHEMA_VERSION = "multicity-platform-v3"
METHODOLOGY_VERSION = "school-led-market-v3.0"
TARGET_CITIES = ("delhi_ncr", "bengaluru", "hyderabad", "mumbai")
CITY_LABELS = {
    "delhi_ncr": "Delhi NCR",
    "bengaluru": "Bengaluru",
    "hyderabad": "Hyderabad",
    "mumbai": "Mumbai",
}
CITY_ALIASES = {
    "delhi ncr": "delhi_ncr",
    "delhi_ncr": "delhi_ncr",
    "delhi-ncr": "delhi_ncr",
    "ncr": "delhi_ncr",
    "bangalore": "bengaluru",
    "bengaluru": "bengaluru",
    "hyderabad": "hyderabad",
    "mumbai": "mumbai",
}
TIERS = ("Super-Premium", "Premium", "Affordable", "Budget")
CATEGORIES = {
    "super_premium": {"label": "Super-Premium", "tiers": ["Super-Premium"]},
    "premium": {"label": "Premium", "tiers": ["Premium"]},
    "affordable": {"label": "Affordable", "tiers": ["Affordable"]},
    "budget": {"label": "Budget", "tiers": ["Budget"]},
    "premium_plus": {
        "label": "Premium + Super-Premium",
        "tiers": ["Super-Premium", "Premium"],
    },
    "affordable_plus": {
        "label": "Affordable and above",
        "tiers": ["Super-Premium", "Premium", "Affordable"],
    },
    "all_private": {"label": "All private schools", "tiers": list(TIERS)},
}
SOURCE_FILES = {
    "schools": "schools/final_schools.csv",
    "projects": "Projects/magicbricks_projects_final_master.csv",
    "hospitals": "hospitals/hospitals_all_cities.csv",
    "localities": "localities/real_estate_localities_and_societies.csv",
    "offices": "offices/offices_unified_all_cities.csv",
}
SCORING_WEIGHTS = {
    "school_demand": 0.55,
    "premium_concentration": 0.15,
    "residential_market_depth": 0.15,
    "office_anchor_depth": 0.10,
    "health_locality_confidence": 0.05,
}
CITY_FALLBACK_CENTERS = {
    "delhi_ncr": {"latitude": 28.6139, "longitude": 77.2090, "zoom": 8},
    "bengaluru": {"latitude": 12.9716, "longitude": 77.5946, "zoom": 10},
    "hyderabad": {"latitude": 17.3850, "longitude": 78.4867, "zoom": 10},
    "mumbai": {"latitude": 19.0760, "longitude": 72.8777, "zoom": 10},
}
CITY_COORDINATE_WINDOWS = {
    "delhi_ncr": {"south": 27.0, "west": 76.0, "north": 29.9, "east": 78.8},
    "bengaluru": {"south": 12.0, "west": 76.7, "north": 14.1, "east": 78.5},
    "hyderabad": {"south": 16.5, "west": 77.5, "north": 18.5, "east": 79.6},
    "mumbai": {"south": 18.6, "west": 72.6, "north": 19.9, "east": 73.7},
}
GEOCODE_OVERRIDE_PATH = Path(__file__).resolve().parent / "public" / "data" / "geocode_overrides" / "society_coordinates.json"
_GEOCODE_OVERRIDES: dict[str, dict[str, Any]] | None = None


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def number(value: Any) -> float | None:
    try:
        parsed = float(clean(value).replace(",", ""))
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def integer(value: Any) -> int | None:
    parsed = number(value)
    return None if parsed is None else int(round(parsed))


def pct(numerator: float, denominator: float) -> float | None:
    return None if denominator == 0 else round(numerator * 100.0 / denominator, 2)


def normalize_city(value: Any) -> str | None:
    key = " ".join(clean(value).lower().replace("_", " ").replace("-", " ").split())
    return CITY_ALIASES.get(key) or CITY_ALIASES.get(clean(value).lower())


def load_geocode_overrides() -> dict[str, dict[str, Any]]:
    global _GEOCODE_OVERRIDES
    if _GEOCODE_OVERRIDES is not None:
        return _GEOCODE_OVERRIDES
    if not GEOCODE_OVERRIDE_PATH.exists():
        _GEOCODE_OVERRIDES = {}
        return _GEOCODE_OVERRIDES
    try:
        payload = json.loads(GEOCODE_OVERRIDE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        _GEOCODE_OVERRIDES = {}
        return _GEOCODE_OVERRIDES
    rows = payload.get("overrides", []) if isinstance(payload, dict) else []
    _GEOCODE_OVERRIDES = {
        clean(row.get("project_id")): row
        for row in rows
        if clean(row.get("project_id"))
    }
    return _GEOCODE_OVERRIDES


def valid_coordinates(row: dict[str, str], lat_key: str = "latitude", lon_key: str = "longitude") -> tuple[float, float] | None:
    lat, lon = number(row.get(lat_key)), number(row.get(lon_key))
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def in_city_window(city_id: str | None, lat: float, lon: float) -> bool:
    if city_id is None:
        return True
    bounds = CITY_COORDINATE_WINDOWS[city_id]
    return bounds["south"] <= lat <= bounds["north"] and bounds["west"] <= lon <= bounds["east"]


def coordinate_candidates(row: dict[str, str], lat_key: str, lon_key: str) -> list[tuple[float, float]]:
    lat, lon = number(row.get(lat_key)), number(row.get(lon_key))
    if lat is None or lon is None:
        return []
    candidates = []
    if -90 <= lat <= 90 and -180 <= lon <= 180:
        candidates.append((lat, lon))
    if -90 <= lon <= 90 and -180 <= lat <= 180:
        candidates.append((lon, lat))
    return candidates


def text_tokens(value: Any) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", clean(value).lower())
        if len(token) >= 3 and token not in {"the", "and", "pvt", "ltd", "llp", "india"}
    }


def source_pincode(value: Any) -> str:
    digits = re.sub(r"\D", "", clean(value))
    return digits[:6] if len(digits) >= 6 else ""


def sector_tokens(value: Any) -> set[str]:
    text = clean(value).lower()
    return {match.replace(" ", "") for match in re.findall(r"sector\s*[a-z0-9]+", text)}


def google_project_candidate_is_trustworthy(row: dict[str, str]) -> bool:
    """Guard against weak free/Google candidates becoming false society points.

    The project source already contains candidate geocodes.  We only use the
    candidate when it passes identity evidence: accepted source flag, exact
    pincode, project-name token overlap, or locality/sector match.  This keeps
    rows like a Gurgaon society candidate geocoded to Connaught Place out of the
    map, while preserving strong sector/project matches.
    """
    if clean(row.get("google_match_accepted")).lower() == "true":
        return True

    rejection = clean(row.get("google_rejection_reasons")).lower()
    if "wrong_state" in rejection or "generic_result_type" in rejection:
        return False

    formatted = " ".join([
        clean(row.get("google_formatted_address")),
        clean(row.get("google_locality")),
        clean(row.get("google_pincode")),
    ]).lower()
    if not formatted:
        return False

    pin = source_pincode(row.get("pincode"))
    google_pin = source_pincode(row.get("google_pincode")) or source_pincode(row.get("google_formatted_address"))
    if pin and google_pin and pin == google_pin:
        return True

    locality_sectors = sector_tokens(row.get("locality"))
    if locality_sectors and locality_sectors & sector_tokens(formatted):
        return True

    name_score = number(row.get("google_name_match_score")) or 0
    name_tokens = text_tokens(row.get("name") or row.get("normalized_name"))
    address_tokens = text_tokens(formatted)
    if name_score >= 0.75 and name_tokens and len(name_tokens & address_tokens) >= min(2, len(name_tokens)):
        return True

    locality_tokens = text_tokens(row.get("locality"))
    if locality_tokens and len(locality_tokens & address_tokens) >= min(2, len(locality_tokens)):
        return True

    return False


def project_coordinate_decision(row: dict[str, str], city_id: str | None = None) -> dict[str, Any] | None:
    override = load_geocode_overrides().get(clean(row.get("project_id")))
    if override:
        lat, lon = number(override.get("lat")), number(override.get("lon"))
        if lat is not None and lon is not None and in_city_window(city_id, lat, lon):
            return {
                "lat": lat,
                "lon": lon,
                "source": clean(override.get("source")) or "free_osm_nominatim",
                "quality": clean(override.get("quality")) or "validated_free_geocode",
            }

    for lat_key, lon_key, source in (
        ("final_latitude", "final_longitude", clean(row.get("final_coordinate_source")) or "final_coordinate"),
        ("latitude", "longitude", "source_coordinate"),
    ):
        for lat, lon in coordinate_candidates(row, lat_key, lon_key):
            if in_city_window(city_id, lat, lon):
                return {"lat": lat, "lon": lon, "source": source, "quality": "source"}

    if google_project_candidate_is_trustworthy(row):
        for lat, lon in coordinate_candidates(row, "google_latitude", "google_longitude"):
            if in_city_window(city_id, lat, lon):
                return {"lat": lat, "lon": lon, "source": "validated_candidate_geocode", "quality": "validated"}

    return None


def row_coordinates(row: dict[str, str], layer: str = "schools", city_id: str | None = None) -> tuple[float, float] | None:
    if layer == "projects":
        decision = project_coordinate_decision(row, city_id)
        return (decision["lat"], decision["lon"]) if decision else None

    key_pairs = [("latitude", "longitude")]
    for lat_key, lon_key in key_pairs:
        for lat, lon in coordinate_candidates(row, lat_key, lon_key):
            if in_city_window(city_id, lat, lon):
                return lat, lon
    return None


def h3_cell(row: dict[str, str], resolution: int = 7, layer: str = "schools", city_id: str | None = None) -> str | None:
    existing = clean(row.get("h3_res7")) if resolution == 7 else ""
    if existing and city_id is None:
        return existing
    coordinates = row_coordinates(row, layer, city_id)
    return h3.latlng_to_cell(*coordinates, resolution) if coordinates else None


def h3_polygon(hex_id: str) -> dict[str, Any]:
    boundary = h3.cell_to_boundary(hex_id)
    coordinates = [[round(lon, 8), round(lat, 8)] for lat, lon in boundary]
    coordinates.append(coordinates[0])
    return {"type": "Polygon", "coordinates": [coordinates]}


def h3_center(hex_id: str) -> dict[str, float]:
    lat, lon = h3.cell_to_latlng(hex_id)
    return {"latitude": round(lat, 6), "longitude": round(lon, 6)}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    value = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def usable_neighborhood_label(value: Any, city_id: str) -> str | None:
    """Return a human market label while rejecting IDs and generic city labels."""
    label = " ".join(clean(value).split()).strip(" ,-–—")
    if not label or label.isdigit() or label.lower().startswith("87") and len(label) >= 12:
        return None
    normalized = label.casefold().replace("_", " ").replace("-", " ")
    generic = {
        CITY_LABELS[city_id].casefold().replace("_", " ").replace("-", " "),
        "bangalore" if city_id == "bengaluru" else "",
        "bengaluru" if city_id == "bengaluru" else "",
        "delhi ncr" if city_id == "delhi_ncr" else "",
        "mumbai city" if city_id == "mumbai" else "",
    }
    if normalized in generic:
        return None
    return label


def row_neighborhood_candidates(
    row: dict[str, str], layer: str, city_id: str,
) -> list[tuple[str, str, int]]:
    """Ordered names with evidence source and selection weight."""
    fields: list[tuple[str, int]]
    if layer == "localities":
        fields = (
            [("name", 120), ("locality", 105)]
            if clean(row.get("entity_type")).lower() == "locality"
            else [("locality", 110), ("name", 80)]
        )
    elif layer == "projects":
        fields = [("locality", 100), ("google_locality", 96), ("sub_city", 75)]
    elif layer == "hospitals":
        fields = [("locality", 92)]
    elif layer == "offices":
        fields = [("locality", 88)]
    else:
        fields = [("area", 86), ("district", 60)]
    output: list[tuple[str, str, int]] = []
    seen: set[str] = set()
    for field, weight in fields:
        label = usable_neighborhood_label(row.get(field), city_id)
        key = label.casefold() if label else ""
        if label and key not in seen:
            output.append((label, f"{layer}.{field}", weight))
            seen.add(key)
    return output


def build_neighborhood_index(
    layers: dict[str, list[dict[str, str]]], city_id: str,
) -> tuple[dict[str, list[tuple[str, str, int]]], list[tuple[float, float, str, str, int]]]:
    by_cell: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
    named_points: list[tuple[float, float, str, str, int]] = []
    for layer, rows in layers.items():
        for row in rows:
            candidates = row_neighborhood_candidates(row, layer, city_id)
            if not candidates:
                continue
            coordinates = row_coordinates(row, layer, city_id)
            cell = h3_cell(row, layer=layer, city_id=city_id)
            if cell:
                by_cell[cell].extend(candidates)
            if coordinates:
                lat, lon = coordinates
                label, source, weight = candidates[0]
                named_points.append((lat, lon, label, source, weight))
    return by_cell, named_points


def choose_neighborhood_name(
    hex_id: str,
    direct_candidates: list[tuple[str, str, int]],
    named_points: list[tuple[float, float, str, str, int]],
    city_id: str,
) -> dict[str, Any]:
    if direct_candidates:
        grouped: dict[str, dict[str, Any]] = {}
        for label, source, weight in direct_candidates:
            key = label.casefold()
            item = grouped.setdefault(
                key, {"label": label, "source": source, "weight": weight, "mentions": 0},
            )
            if weight > item["weight"]:
                item["label"], item["source"], item["weight"] = label, source, weight
            item["mentions"] += 1
        winner = sorted(
            grouped.values(),
            key=lambda item: (-item["weight"], -item["mentions"], item["label"].casefold()),
        )[0]
        if winner["weight"] >= 75:
            return {
                "name": winner["label"],
                "source": winner["source"],
                "confidence": "high" if winner["weight"] >= 100 else "medium",
                "distance_km": 0.0,
            }
        low_specificity_winner = winner
    else:
        low_specificity_winner = None

    center = h3_center(hex_id)
    nearest = None
    for lat, lon, label, source, weight in named_points:
        if weight < 75:
            continue
        distance = haversine_km(center["latitude"], center["longitude"], lat, lon)
        candidate = (round(distance, 4), -weight, label.casefold(), label, source)
        if nearest is None or candidate < nearest:
            nearest = candidate
    if nearest is not None:
        distance, _negative_weight, _key, label, source = nearest
        return {
            "name": f"Near {label}",
            "source": f"nearest:{source}",
            "confidence": "medium" if distance <= 2.5 else "low",
            "distance_km": round(distance, 2),
        }
    if low_specificity_winner is not None:
        return {
            "name": low_specificity_winner["label"],
            "source": low_specificity_winner["source"],
            "confidence": "low",
            "distance_km": 0.0,
        }
    return {
        "name": f"{CITY_LABELS[city_id]} market cell {hex_id[-5:]}",
        "source": "h3_fallback",
        "confidence": "low",
        "distance_km": None,
    }


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def nullable_sum(values: Iterable[float | None]) -> int | None:
    """Sum known values while preserving an entirely unknown cohort as null."""
    known = [value for value in values if value is not None]
    return int(round(sum(known))) if known else None


def source_reported(row: dict[str, str]) -> bool:
    """True only when the source supplied total enrollment for the school."""
    return clean(row.get("enrollment_source")) == "UDISE_reported_total"


def project_identity(row: dict[str, str]) -> str:
    """Stable logical project identity that disambiguates reused source IDs.

    The source contains a small number of project IDs reused across different
    Bengaluru localities.  Including normalized name and location prevents
    those projects from being collapsed while still collapsing repeated rows
    for the same project/listing group.
    """
    duplicate_group = clean(row.get("duplicate_group_id"))
    if duplicate_group:
        return f"duplicate_group:{duplicate_group}"
    parts = (
        clean(row.get("canonical_city_id") or row.get("city")).casefold(),
        clean(row.get("project_id") or row.get("source_project_id")).casefold(),
        clean(row.get("normalized_name") or row.get("name")).casefold(),
        clean(row.get("locality")).casefold(),
        source_pincode(row.get("pincode")),
    )
    return "|".join(parts)


def unique_projects(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    """Return one best-evidenced row per logical residential project."""
    selected: dict[str, dict[str, str]] = {}
    for row in rows:
        key = project_identity(row)
        incumbent = selected.get(key)
        if incumbent is None:
            selected[key] = row
            continue
        incumbent_evidence = (
            number(incumbent.get("total_units")) is not None,
            valid_coordinates(incumbent, "final_latitude", "final_longitude") is not None,
            bool(clean(incumbent.get("source_url"))),
        )
        candidate_evidence = (
            number(row.get("total_units")) is not None,
            valid_coordinates(row, "final_latitude", "final_longitude") is not None,
            bool(clean(row.get("source_url"))),
        )
        if candidate_evidence > incumbent_evidence:
            selected[key] = row
    return [selected[key] for key in sorted(selected)]


def campus_scenarios(students_grade_2_9: int | None) -> list[dict[str, Any]]:
    """Planning scenarios based only on reported-school Grade 2-9 derivations."""
    output = []
    for capture_rate in (0.01, 0.02, 0.03):
        captured = None if students_grade_2_9 is None else round(students_grade_2_9 * capture_rate, 2)
        effective_capacity = 200 * 0.8
        output.append({
            "scenario_type": "planning_scenario",
            "evidence_basis": "derived_grade_2_9_from_source_reported_total_enrollment",
            "capture_rate": capture_rate,
            "capture_rate_pct": int(capture_rate * 100),
            "captured_students": captured,
            "campuses_supported": (
                math.floor(captured / effective_capacity)
                if captured is not None and effective_capacity else None
            ),
            "seats_per_campus": 200,
            "target_utilization": 0.8,
            "effective_students_per_campus": int(effective_capacity),
        })
    return output


def school_category_metrics(
    rows: Iterable[dict[str, str]],
    all_city_students: int | None = None,
    city_id: str | None = None,
) -> dict[str, Any]:
    records = list(rows)
    school_count = len(records)
    grade_values = [number(row.get("enrollment_grade_2_9")) for row in records]
    total_values = [number(row.get("enrollment_total")) for row in records]
    combined_grade_students = nullable_sum(grade_values) if records else 0
    reported_total_students = nullable_sum(
        total_values[index]
        for index, row in enumerate(records)
        if source_reported(row) and total_values[index] is not None
    ) if records else 0
    reported_grade_students = nullable_sum(
        grade_values[index]
        for index, row in enumerate(records)
        if source_reported(row) and grade_values[index] is not None
    ) if records else 0
    modeled_grade_students = nullable_sum(
        grade_values[index]
        for index, row in enumerate(records)
        if not source_reported(row) and grade_values[index] is not None
    ) if records else 0
    with_coordinates = sum(row_coordinates(row, "schools", city_id) is not None for row in records)
    with_verified_coordinates = sum(
        clean(row.get("coordinate_quality")) == "verified_google_places"
        and row_coordinates(row, "schools", city_id) is not None
        for row in records
    )
    return {
        "school_count": school_count,
        # Compatibility aggregate. Never use this field for ranking or a
        # primary headline; it can include modeled rows.
        "students_grade_2_9": combined_grade_students,
        "combined_students_grade_2_9": combined_grade_students,
        "enrollment_total": reported_total_students,
        "reported_enrollment_total": reported_total_students,
        "reported_students_grade_2_9": reported_grade_students,
        "modeled_students_grade_2_9": modeled_grade_students,
        "primary_evidence_metric": "reported_enrollment_total",
        "grade_2_9_method": "derived_from_source_reported_total_enrollment",
        "student_share_of_city_private_pct": (
            pct(reported_grade_students, all_city_students)
            if reported_grade_students is not None and all_city_students is not None else None
        ),
        "campus_scenarios": campus_scenarios(reported_grade_students),
        "coverage": {
            "schools_with_grade_2_9_count": sum(value is not None for value in grade_values),
            "schools_with_grade_2_9_pct": pct(sum(value is not None for value in grade_values), school_count),
            "schools_with_total_enrollment_count": sum(value is not None for value in total_values),
            "schools_with_total_enrollment_pct": pct(sum(value is not None for value in total_values), school_count),
            "schools_with_coordinates_count": with_coordinates,
            "schools_with_coordinates_pct": pct(with_coordinates, school_count),
            "verified_coordinate_count": with_verified_coordinates,
            "verified_coordinate_pct": pct(with_verified_coordinates, school_count),
            "source_reported_school_count": sum(source_reported(row) for row in records),
            "source_reported_school_pct": pct(sum(source_reported(row) for row in records), school_count),
            "reported_grade_2_9_students": reported_grade_students,
            "estimated_grade_2_9_students": modeled_grade_students,
            "modeled_grade_2_9_students": modeled_grade_students,
            "estimated_grade_2_9_share_pct": (
                pct(modeled_grade_students, combined_grade_students)
                if modeled_grade_students is not None and combined_grade_students is not None else None
            ),
        },
    }


def category_metrics(rows: list[dict[str, str]], city_id: str | None = None) -> dict[str, Any]:
    all_students = (
        nullable_sum(
            number(row.get("enrollment_grade_2_9"))
            for row in rows if source_reported(row)
        )
        if rows else 0
    )
    output = {}
    for category_id, definition in CATEGORIES.items():
        selected = [row for row in rows if clean(row.get("fee_tier")) in definition["tiers"]]
        output[category_id] = school_category_metrics(selected, all_students, city_id)
    return output


def compact_category_metrics(rows: list[dict[str, str]]) -> dict[str, Any]:
    """Small spatial payload; city-level artifacts carry full QA/scenarios."""
    output = {}
    for category_id, definition in CATEGORIES.items():
        selected = [row for row in rows if clean(row.get("fee_tier")) in definition["tiers"]]
        combined_students = (
            nullable_sum(number(row.get("enrollment_grade_2_9")) for row in selected)
            if selected else 0
        )
        reported_students = (
            nullable_sum(
                number(row.get("enrollment_grade_2_9"))
                for row in selected if source_reported(row)
            ) if selected else 0
        )
        reported_total = (
            nullable_sum(
                number(row.get("enrollment_total"))
                for row in selected if source_reported(row)
            ) if selected else 0
        )
        modeled_students = (
            nullable_sum(
                number(row.get("enrollment_grade_2_9"))
                for row in selected if not source_reported(row)
            ) if selected else 0
        )
        output[category_id] = {
            "school_count": len(selected),
            "students_grade_2_9": combined_students,
            "combined_students_grade_2_9": combined_students,
            "reported_enrollment_total": reported_total,
            "reported_students_grade_2_9": reported_students,
            "modeled_students_grade_2_9": modeled_students,
        }
    return output


def delhi_component(row: dict[str, str]) -> str:
    state, district = clean(row.get("state")).upper(), clean(row.get("district")).upper()
    if state == "DELHI":
        return "delhi"
    if district == "GURUGRAM":
        return "gurugram"
    if district == "FARIDABAD":
        return "faridabad"
    if district == "GAUTAM BUDDHA NAGAR":
        return "noida_greater_noida"
    if district == "GHAZIABAD":
        return "ghaziabad"
    if district == "HAPUR":
        return "hapur"
    if district == "PALWAL":
        return "palwal"
    if district == "BULANDSHAHR":
        return "bulandshahr"
    if district == "MEERUT":
        return "meerut"
    return "unassigned"


def aggregate_school_geography(
    rows: list[dict[str, str]],
    key_function,
    label_function=None,
    city_id: str | None = None,
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        key = clean(key_function(row))
        if key:
            groups[key].append(row)
    output = []
    for key, group in groups.items():
        coordinates = [row_coordinates(row, "schools", city_id) for row in group]
        coordinates = [item for item in coordinates if item is not None]
        reported_rows = [row for row in group if source_reported(row)]
        item = {
            "id": key,
            "label": label_function(key, group) if label_function else key,
            "school_count": len(group),
            "students_grade_2_9": nullable_sum(
                number(row.get("enrollment_grade_2_9")) for row in group
            ),
            "reported_enrollment_total": nullable_sum(
                number(row.get("enrollment_total")) for row in reported_rows
            ),
            "reported_students_grade_2_9": nullable_sum(
                number(row.get("enrollment_grade_2_9")) for row in reported_rows
            ),
            "modeled_students_grade_2_9": nullable_sum(
                number(row.get("enrollment_grade_2_9"))
                for row in group if not source_reported(row)
            ),
            "center": {
                "latitude": round(sum(point[0] for point in coordinates) / len(coordinates), 6),
                "longitude": round(sum(point[1] for point in coordinates) / len(coordinates), 6),
            } if coordinates else None,
            "category_metrics": compact_category_metrics(group),
        }
        output.append(item)
    return sorted(
        output,
        key=lambda item: (
            item["reported_enrollment_total"] is None,
            -(item["reported_enrollment_total"] or 0),
            item["id"],
        ),
    )


def layer_summary(rows: list[dict[str, str]], layer: str, city_id: str) -> dict[str, Any]:
    total = len(rows)
    raw_coordinate_count = sum(row_coordinates(row, layer) is not None for row in rows)
    coordinate_count = sum(row_coordinates(row, layer, city_id) is not None for row in rows)
    result: dict[str, Any] = {
        "record_count": total,
        "coordinate_count": coordinate_count,
        "coordinate_coverage_pct": pct(coordinate_count, total),
        "raw_coordinate_count": raw_coordinate_count,
        "out_of_market_coordinate_count": max(0, raw_coordinate_count - coordinate_count),
    }
    if layer == "projects":
        projects = unique_projects(rows)
        source_ids = [clean(row.get("project_id")) for row in rows if clean(row.get("project_id"))]
        source_id_counts = Counter(source_ids)
        units = [number(row.get("total_units")) for row in projects]
        known_units = nullable_sum(units) if projects else 0
        result.update({
            "record_count": len(projects),
            "source_listing_count": total,
            "duplicate_listing_count": total - len(projects),
            "canonical_project_count": len(projects),
            "source_project_id_count": len(set(source_ids)),
            "reused_source_project_id_count": sum(count > 1 for count in source_id_counts.values()),
            "projects_with_known_units_count": sum(value is not None for value in units),
            "projects_with_known_units_pct": pct(sum(value is not None for value in units), len(projects)),
            "known_residential_units": known_units,
            "inventory_measure": "known_project_units",
        })
    elif layer == "offices":
        result.update({
            "tier_1_office_count": sum(clean(row.get("company_prominence_tier")) == "Tier-1" for row in rows),
            "active_office_count": sum(clean(row.get("is_active")).lower() == "true" for row in rows),
        })
    elif layer == "hospitals":
        result.update({
            "multispeciality_count": sum(clean(row.get("multispeciality")).lower() == "true" for row in rows),
            "doctors_known_count": sum(number(row.get("doctors_count")) is not None for row in rows),
        })
    elif layer == "localities":
        types = Counter(clean(row.get("entity_type")) or "unknown" for row in rows)
        result["entity_type_counts"] = dict(sorted(types.items()))
    return result


def layer_h3_groups(rows: list[dict[str, str]], layer: str, city_id: str) -> dict[str, list[dict[str, str]]]:
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        cell = h3_cell(row, layer=layer, city_id=city_id)
        if cell:
            groups[cell].append(row)
    return groups


def numeric_average(values: Iterable[float | None]) -> float | None:
    known = [value for value in values if value is not None]
    return round(sum(known) / len(known), 2) if known else None


def project_metrics(rows: list[dict[str, str]]) -> dict[str, Any]:
    source_rows = rows
    rows = unique_projects(source_rows)
    source_ids = [clean(row.get("project_id")) for row in source_rows if clean(row.get("project_id"))]
    source_id_counts = Counter(source_ids)
    units = [number(row.get("total_units")) for row in rows]
    q4 = [row for row in rows if clean(row.get("final_quartile") or row.get("quartile")) == "Q4"]
    q3_below = [
        row for row in rows
        if clean(row.get("final_quartile") or row.get("quartile")) in {"Q1", "Q2", "Q3"}
    ]
    return {
        "project_count": len(rows),
        "canonical_project_count": len(rows),
        "source_project_id_count": len(set(source_ids)),
        "reused_source_project_id_count": sum(count > 1 for count in source_id_counts.values()),
        "known_units": nullable_sum(units) if rows else 0,
        "known_units_project_count": sum(value is not None for value in units),
        "known_units_coverage_pct": pct(sum(value is not None for value in units), len(rows)),
        "q4_project_count": len(q4),
        "q3_and_below_project_count": len(q3_below),
    }


def office_metrics(rows: list[dict[str, str]]) -> dict[str, Any]:
    def is_tier_1(row: dict[str, str]) -> bool:
        tier = clean(row.get("company_prominence_tier")).lower()
        return tier in {"tier-1", "tier 1"} or tier.startswith("tier 1")

    return {
        "office_count": len(rows),
        "tier_1_office_count": sum(is_tier_1(row) for row in rows),
        "active_office_count": sum(clean(row.get("is_active")).lower() == "true" for row in rows),
        "avg_prominence_score": numeric_average(number(row.get("company_prominence_score")) for row in rows),
    }


def hospital_metrics(rows: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "hospital_count": len(rows),
        "multispeciality_count": sum(clean(row.get("multispeciality")).lower() == "true" for row in rows),
        "avg_hospital_score": numeric_average(number(row.get("hospital_score")) for row in rows),
    }


def locality_metrics(rows: list[dict[str, str]]) -> dict[str, Any]:
    prices = [number(row.get("price_per_sqft_avg")) for row in rows]
    societies = sum(clean(row.get("entity_type")).lower() == "society" for row in rows)
    return {
        "locality_record_count": len(rows),
        "society_record_count": societies,
        "avg_price_per_sqft": numeric_average(prices),
        "known_price_record_count": sum(value is not None for value in prices),
    }


def compact_context_metrics(
    projects: list[dict[str, str]],
    offices: list[dict[str, str]],
    hospitals: list[dict[str, str]],
    localities: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "projects": project_metrics(projects),
        "offices": office_metrics(offices),
        "hospitals": hospital_metrics(hospitals),
        "localities": locality_metrics(localities),
    }


def hex_category_scores(
    records: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    if not records:
        return {}
    output = {record["hex_id"]: {} for record in records}
    for category_id in CATEGORIES:
        normalized = {
            "school_demand": robust_normalized_scores([
                record["category_metrics"][category_id]["reported_students_grade_2_9"]
                for record in records
            ]),
            "residential_market_depth": robust_normalized_scores([
                record["context"]["projects"]["known_units"]
                for record in records
            ]),
            "office_anchor_depth": robust_normalized_scores([
                record["context"]["offices"]["tier_1_office_count"]
                for record in records
            ]),
            "hospital_depth": robust_normalized_scores([
                record["context"]["hospitals"]["hospital_count"]
                for record in records
            ]),
            "locality_depth": robust_normalized_scores([
                record["context"]["localities"]["locality_record_count"]
                for record in records
            ]),
        }
        for index, record in enumerate(records):
            selected_students = record["category_metrics"][category_id]["reported_students_grade_2_9"]
            all_students = record["category_metrics"]["all_private"]["reported_students_grade_2_9"]
            health_locality = numeric_average(
                [
                    normalized["hospital_depth"][index],
                    normalized["locality_depth"][index],
                ]
            )
            components = {
                "school_demand": normalized["school_demand"][index],
                "premium_concentration": (
                    pct(selected_students, all_students)
                    if selected_students is not None and all_students not in (None, 0)
                    else None
                ),
                "residential_market_depth": normalized["residential_market_depth"][index],
                "office_anchor_depth": normalized["office_anchor_depth"][index],
                "health_locality_confidence": health_locality,
            }
            known_weight = sum(
                weight for key, weight in SCORING_WEIGHTS.items()
                if components.get(key) is not None
            )
            weighted_score = (
                round(
                    sum(
                        SCORING_WEIGHTS[key] * components[key]
                        for key in SCORING_WEIGHTS
                        if components.get(key) is not None
                    ) / known_weight,
                    2,
                )
                if known_weight else None
            )
            output[record["hex_id"]][category_id] = {
                "category_id": category_id,
                "weighted_score": weighted_score,
                "score_weight_coverage_pct": round(known_weight * 100.0, 2),
                "normalization": "log_p5_p95_by_city_category_for_h3_metrics",
                "components": components,
                "weights": SCORING_WEIGHTS,
            }
    return output


def city_map_geometry(layer_rows: dict[str, list[dict[str, str]]], city_id: str) -> dict[str, Any]:
    points = []
    for layer, rows in layer_rows.items():
        for row in rows:
            coordinates = row_coordinates(row, layer, city_id)
            if coordinates:
                points.append(coordinates)
    fallback = CITY_FALLBACK_CENTERS[city_id]
    if not points:
        return {
            "center": {"latitude": fallback["latitude"], "longitude": fallback["longitude"]},
            "bounds": None,
            "zoom": fallback["zoom"],
        }
    lats = [point[0] for point in points]
    lons = [point[1] for point in points]
    return {
        "center": {
            "latitude": round(sum(lats) / len(lats), 6),
            "longitude": round(sum(lons) / len(lons), 6),
        },
        "bounds": {
            "south": round(min(lats), 6),
            "west": round(min(lons), 6),
            "north": round(max(lats), 6),
            "east": round(max(lons), 6),
        },
        "zoom": fallback["zoom"],
    }


def quality_warnings(summary: dict[str, Any]) -> list[str]:
    warnings = list(summary["quality"]["flags"])
    context = summary["context_layers"]
    if any((layer.get("out_of_market_coordinate_count") or 0) > 0 for layer in context.values()):
        warnings.append("out_of_market_coordinates_excluded_from_map")
    if (context["projects"]["coordinate_coverage_pct"] or 0) < 50:
        warnings.append("low_project_coordinate_coverage")
    if context["localities"]["record_count"] < 50:
        warnings.append("thin_locality_context")
    if (context["hospitals"]["coordinate_coverage_pct"] or 0) < 90:
        warnings.append("hospital_coordinate_coverage_review")
    return sorted(set(warnings))


def normalize_score(value: float | int | None, maximum: float | int | None) -> float | None:
    if value is None or maximum in (None, 0):
        return None
    return round(max(0.0, min(100.0, float(value) * 100.0 / float(maximum))), 2)


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[int(position)]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def robust_normalized_scores(values: list[float | int | None]) -> list[float | None]:
    logged = [None if value is None else math.log1p(max(0.0, float(value))) for value in values]
    positives = [value for value in logged if value is not None and value > 0]
    if not positives:
        return [None if value is None else 0.0 for value in values]
    lo = percentile(positives, 5) or 0.0
    hi = percentile(positives, 95) or lo
    if hi <= lo:
        return [None if value is None else (100.0 if value > 0 else 0.0) for value in values]
    output: list[float | None] = []
    for value in logged:
        if value is None:
            output.append(None)
        elif value <= 0:
            output.append(0.0)
        else:
            clipped = min(max(value, lo), hi)
            output.append(round((clipped - lo) * 100.0 / (hi - lo), 2))
    return output


def build_scores(city_summaries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    candidates = [row for row in city_summaries if row["canonical_city_id"] != "delhi_ncr"]
    output: dict[str, dict[str, Any]] = {row["canonical_city_id"]: {} for row in city_summaries}
    for category_id in CATEGORIES:
        maxima = {
            "school_demand": max(
                (row["category_metrics"][category_id]["reported_enrollment_total"] or 0)
                for row in candidates
            ) or None,
            "premium_concentration": max(
                (row["spatial_concentration"][category_id]["top_10_h3_student_share_pct"] or 0)
                for row in candidates
            ) or None,
            "residential_market_depth": max(
                (row["context_layers"]["projects"]["known_residential_units"] or 0)
                for row in candidates
            ) or None,
            "office_anchor_depth": max(
                (row["context_layers"]["offices"]["tier_1_office_count"] or 0)
                for row in candidates
            ) or None,
            "health_locality_confidence": 100,
        }
        scored_rows = []
        for row in city_summaries:
            city_id = row["canonical_city_id"]
            category = row["category_metrics"][category_id]
            context = row["context_layers"]
            coverage_values = [
                category["coverage"].get("schools_with_grade_2_9_pct"),
                context["projects"].get("coordinate_coverage_pct"),
                context["hospitals"].get("coordinate_coverage_pct"),
                context["localities"].get("coordinate_coverage_pct"),
            ]
            confidence_value = numeric_average(value for value in coverage_values if value is not None)
            components = {
                "school_demand": normalize_score(category["reported_enrollment_total"], maxima["school_demand"]),
                "premium_concentration": normalize_score(
                    row["spatial_concentration"][category_id]["top_10_h3_student_share_pct"],
                    maxima["premium_concentration"],
                ),
                "residential_market_depth": normalize_score(
                    context["projects"]["known_residential_units"],
                    maxima["residential_market_depth"],
                ),
                "office_anchor_depth": normalize_score(
                    context["offices"]["tier_1_office_count"],
                    maxima["office_anchor_depth"],
                ),
                "health_locality_confidence": confidence_value,
            }
            known_weight = sum(
                weight for key, weight in SCORING_WEIGHTS.items()
                if components.get(key) is not None
            )
            weighted_score = (
                round(
                    sum(SCORING_WEIGHTS[key] * components[key] for key in SCORING_WEIGHTS if components.get(key) is not None)
                    / known_weight,
                    2,
                )
                if known_weight else None
            )
            score_payload = {
                "category_id": category_id,
                "status": "benchmark" if city_id == "delhi_ncr" else "candidate",
                "weighted_score": weighted_score,
                "score_weight_coverage_pct": round(known_weight * 100.0, 2),
                "weights": SCORING_WEIGHTS,
                "components": components,
                "warnings": quality_warnings(row),
            }
            output[city_id][category_id] = score_payload
            if city_id != "delhi_ncr" and weighted_score is not None:
                scored_rows.append((weighted_score, city_id))
        scored_rows.sort(key=lambda item: (-item[0], item[1]))
        for rank, (_score, city_id) in enumerate(scored_rows, start=1):
            output[city_id][category_id]["candidate_rank"] = rank
            output[city_id][category_id]["recommendation_status"] = (
                "front_runner" if rank == 1 else "shortlist" if rank <= 3 else "watch"
            )
        output["delhi_ncr"][category_id]["candidate_rank"] = None
        output["delhi_ncr"][category_id]["recommendation_status"] = "current_market_benchmark"
    return output


def build_h3_features(city_id: str, layers: dict[str, list[dict[str, str]]]) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    schools_by_h3 = layer_h3_groups(layers["schools"], "schools", city_id)
    projects_by_h3 = layer_h3_groups(layers["projects"], "projects", city_id)
    offices_by_h3 = layer_h3_groups(layers["offices"], "offices", city_id)
    hospitals_by_h3 = layer_h3_groups(layers["hospitals"], "hospitals", city_id)
    localities_by_h3 = layer_h3_groups(layers["localities"], "localities", city_id)
    neighborhood_candidates, named_points = build_neighborhood_index(layers, city_id)
    all_cells = sorted(set().union(schools_by_h3, projects_by_h3, offices_by_h3, hospitals_by_h3, localities_by_h3))
    records = []
    for hex_id in all_cells:
        school_rows = schools_by_h3.get(hex_id, [])
        category_data = compact_category_metrics(school_rows)
        context_data = compact_context_metrics(
            projects_by_h3.get(hex_id, []),
            offices_by_h3.get(hex_id, []),
            hospitals_by_h3.get(hex_id, []),
            localities_by_h3.get(hex_id, []),
        )
        neighborhood = choose_neighborhood_name(
            hex_id,
            neighborhood_candidates.get(hex_id, []),
            named_points,
            city_id,
        )
        properties = {
            "canonical_city_id": city_id,
            "city_label": CITY_LABELS[city_id],
            "hex_id": hex_id,
            "name": neighborhood["name"],
            "neighborhood_name": neighborhood["name"],
            "neighborhood_name_source": neighborhood["source"],
            "neighborhood_name_confidence": neighborhood["confidence"],
            "neighborhood_name_distance_km": neighborhood["distance_km"],
            "center": h3_center(hex_id),
            "school_count": len(school_rows),
            "students_grade_2_9": nullable_sum(number(row.get("enrollment_grade_2_9")) for row in school_rows) if school_rows else 0,
            "reported_enrollment_total": nullable_sum(
                number(row.get("enrollment_total"))
                for row in school_rows if source_reported(row)
            ) if school_rows else 0,
            "reported_students_grade_2_9": nullable_sum(
                number(row.get("enrollment_grade_2_9"))
                for row in school_rows if source_reported(row)
            ) if school_rows else 0,
            "category_metrics": category_data,
            "context": context_data,
        }
        records.append(properties)
    scores = hex_category_scores(records)
    features = []
    by_category = {category_id: [] for category_id in CATEGORIES}
    for properties in records:
        properties["category_scores"] = scores[properties["hex_id"]]
        properties["primary_score"] = scores[properties["hex_id"]]["premium_plus"]
        feature = {"type": "Feature", "geometry": h3_polygon(properties["hex_id"]), "properties": properties}
        features.append(feature)
        for category_id in CATEGORIES:
            if (properties["category_metrics"][category_id]["reported_students_grade_2_9"] or 0) > 0:
                by_category[category_id].append(feature)
    for category_id, category_features in by_category.items():
        category_features.sort(
            key=lambda feature: (
                -(feature["properties"]["category_scores"][category_id]["weighted_score"] or 0),
                -(feature["properties"]["category_metrics"][category_id]["reported_students_grade_2_9"] or 0),
                feature["properties"]["hex_id"],
            )
        )
    return features, by_category


def compact_cluster_feature(feature: dict[str, Any], category_id: str, rank: int) -> dict[str, Any]:
    props = feature["properties"]
    metric = props["category_metrics"][category_id]
    context = props["context"]
    score = props["category_scores"][category_id]
    return {
        "rank": rank,
        "hex_id": props["hex_id"],
        "name": props["neighborhood_name"],
        "center": props["center"],
        "score": score["weighted_score"],
        "score_components": score["components"],
        "students_grade_2_9": metric["students_grade_2_9"],
        "reported_enrollment_total": metric["reported_enrollment_total"],
        "reported_students_grade_2_9": metric["reported_students_grade_2_9"],
        "modeled_students_grade_2_9": metric["modeled_students_grade_2_9"],
        "school_count": metric["school_count"],
        "residential_projects": context["projects"]["project_count"],
        "known_residential_units": context["projects"]["known_units"],
        "office_anchors": context["offices"]["office_count"],
        "tier_1_offices": context["offices"]["tier_1_office_count"],
        "hospitals": context["hospitals"]["hospital_count"],
        "locality_records": context["localities"]["locality_record_count"],
        "neighborhood_name_confidence": props["neighborhood_name_confidence"],
        "neighborhood_name_source": props["neighborhood_name_source"],
    }


def public_project_id(row: dict[str, str]) -> str:
    return "project_" + hashlib.sha1(project_identity(row).encode("utf-8")).hexdigest()[:16]


def build_decision_support(
    city_id: str,
    layers: dict[str, list[dict[str, str]]],
    category_features: list[dict[str, Any]],
) -> dict[str, Any]:
    """Publish named, source-grounded action lists for client workflows."""
    premium_rows = [
        row for row in layers["schools"]
        if clean(row.get("fee_tier")) in CATEGORIES["premium_plus"]["tiers"]
        and source_reported(row)
    ]
    school_rows = sorted(
        premium_rows,
        key=lambda row: (
            -(number(row.get("enrollment_total")) or 0),
            clean(row.get("school_name")).casefold(),
            clean(row.get("school_id")),
        ),
    )
    seen_schools: set[str] = set()
    priority_schools = []
    for row in school_rows:
        school_id = clean(row.get("school_id")) or clean(row.get("udise_code"))
        identity = "|".join((school_id, clean(row.get("school_name")).casefold()))
        if identity in seen_schools:
            continue
        seen_schools.add(identity)
        point = row_coordinates(row, "schools", city_id)
        priority_schools.append({
            "rank": len(priority_schools) + 1,
            "school_id": school_id or None,
            "name": clean(row.get("school_name")) or "Unnamed school",
            "area": clean(row.get("area")) or clean(row.get("district")) or None,
            "district": clean(row.get("district")) or None,
            "board": clean(row.get("board")) or None,
            "fee_tier": clean(row.get("fee_tier")) or None,
            "reported_enrollment_total": integer(row.get("enrollment_total")),
            "reported_students_grade_2_9": integer(row.get("enrollment_grade_2_9")),
            "grade_2_9_method": "derived_from_source_reported_total_enrollment",
            "latitude": point[0] if point else None,
            "longitude": point[1] if point else None,
        })
        if len(priority_schools) == 25:
            break

    project_rows = sorted(
        unique_projects(layers["projects"]),
        key=lambda row: (
            clean(row.get("final_quartile") or row.get("quartile")) != "Q4",
            -(number(row.get("total_units")) or 0),
            clean(row.get("name")).casefold(),
        ),
    )
    residential_targets = []
    for row in project_rows:
        point = row_coordinates(row, "projects", city_id)
        residential_targets.append({
            "rank": len(residential_targets) + 1,
            "project_id": public_project_id(row),
            "source_project_id": clean(row.get("project_id")) or clean(row.get("source_project_id")) or None,
            "name": clean(row.get("name")) or "Unnamed residential project",
            "developer": clean(row.get("developer")) or None,
            "locality": clean(row.get("locality")) or None,
            "quartile": clean(row.get("final_quartile") or row.get("quartile")) or None,
            "known_units": integer(row.get("total_units")),
            "unit_measure": "project_inventory_units",
            "latitude": point[0] if point else None,
            "longitude": point[1] if point else None,
            "source_url": clean(row.get("source_url")) or None,
        })
        if len(residential_targets) == 25:
            break

    corridor_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in premium_rows:
        label = clean(row.get("area")) or clean(row.get("district")) or clean(row.get("pincode"))
        if label:
            corridor_groups[label].append(row)
    corridors = []
    for label, rows in corridor_groups.items():
        corridors.append({
            "name": label,
            "reported_school_count": len(rows),
            "reported_enrollment_total": nullable_sum(number(row.get("enrollment_total")) for row in rows),
            "reported_students_grade_2_9": nullable_sum(number(row.get("enrollment_grade_2_9")) for row in rows),
        })
    corridors.sort(key=lambda row: (-(row["reported_enrollment_total"] or 0), row["name"].casefold()))

    catchments = []
    for feature in category_features[:15]:
        props = feature["properties"]
        metric = props["category_metrics"]["premium_plus"]
        catchments.append({
            "rank": len(catchments) + 1,
            "hex_id": props["hex_id"],
            "name": props["neighborhood_name"],
            "center": props["center"],
            "reported_enrollment_total": metric["reported_enrollment_total"],
            "reported_students_grade_2_9": metric["reported_students_grade_2_9"],
            "modeled_students_grade_2_9": metric["modeled_students_grade_2_9"],
            "school_count": metric["school_count"],
            "residential_project_count": props["context"]["projects"]["project_count"],
            "known_residential_units": props["context"]["projects"]["known_units"],
        })

    primary_metric = school_category_metrics(premium_rows, city_id=city_id)
    return {
        "evidence_policy": {
            "primary_city_metric": "reported_enrollment_total",
            "campus_scenario_basis": "reported_students_grade_2_9",
            "modeled_enrollment_in_primary_rankings": False,
            "residential_measure": "known_project_units",
            "source_observation_as_of": None,
            "academic_year": None,
        },
        "priority_school_partners": priority_schools,
        "residential_project_targets": residential_targets,
        "premium_student_corridors": corridors[:15],
        "candidate_catchments": catchments,
        "campus_scenarios": primary_metric["campus_scenarios"],
    }


def city_local_insights(
    city_id: str,
    detail: dict[str, Any],
    by_category: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    category_insights = {}
    for category_id, features in by_category.items():
        metrics = detail["category_metrics"][category_id]
        score = detail["expansion_scores"][category_id]
        clusters = [compact_cluster_feature(feature, category_id, index + 1) for index, feature in enumerate(features[:12])]
        top_names = [cluster["name"] for cluster in clusters[:3]]
        context = detail["context_layers"]
        city_role = (
            "current_market_benchmark" if city_id == "delhi_ncr"
            else score.get("recommendation_status") or "candidate"
        )
        category_insights[category_id] = {
            "category_id": category_id,
            "category_label": CATEGORIES[category_id]["label"],
            "city_role": city_role,
            "headline": (
                f"{CITY_LABELS[city_id]} has {metrics['reported_enrollment_total'] or 0:,} source-reported students "
                f"in {CATEGORIES[category_id]['label']} schools across {metrics['coverage']['source_reported_school_count']:,} reporting schools."
            ),
            "client_summary": (
                f"Best localized evidence is concentrated around {', '.join(top_names)}."
                if top_names else
                "No mapped school demand cells are available for this selected bucket."
            ),
            "why_this_city": [
                {
                    "label": "School demand",
                    "value": metrics["reported_enrollment_total"],
                    "unit": "source-reported students",
                    "note": f"{metrics['reported_students_grade_2_9'] or 0:,} derived Grades 2-9",
                },
                {
                    "label": "Residential depth",
                    "value": context["projects"]["record_count"],
                    "unit": "project records",
                    "note": (
                        "Known units unavailable"
                        if context["projects"].get("known_residential_units") is None
                        else f"{context['projects']['known_residential_units']:,} known units"
                    ),
                },
                {
                    "label": "Workplace anchors",
                    "value": context["offices"]["record_count"],
                    "unit": "office records",
                    "note": f"{context['offices'].get('tier_1_office_count', 0):,} tier-1 anchors",
                },
                {
                    "label": "Decision confidence",
                    "value": score["score_weight_coverage_pct"],
                    "unit": "% score evidence",
                    "note": "; ".join(score.get("warnings") or ["No major warnings"]),
                },
            ],
            "top_clusters": clusters,
            "recommended_next_step": (
                "Use as the Delhi NCR benchmark to calibrate capture, pricing, and center economics."
                if city_id == "delhi_ncr" else
                "Field-check the top clusters with competition, rents, and drive-time catchments before committing centers."
            ),
        }
    return {
        "schema_version": "city-local-insights-v1",
        "primary_category_id": "premium_plus",
        "categories": category_insights,
    }


def source_metadata(path: Path, logical_path: str, row_count: int) -> dict[str, Any]:
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    return {
        "file": logical_path,
        "filename": path.name,
        "row_count": row_count,
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
        "file_modified_at": modified,
        "source_observation_as_of": None,
        "academic_year": None,
        "date_note": "The source does not publish a verified observation date or academic year in this dataset.",
    }


def artifact_metadata(path: Path, output_root: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(output_root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        handle.write("\n")


def build(data_root: Path, output_root: Path) -> None:
    raw: dict[str, list[dict[str, str]]] = {}
    provenance: dict[str, Any] = {}
    for layer, relative_path in SOURCE_FILES.items():
        path = data_root / relative_path
        if not path.exists():
            raise FileNotFoundError(f"Required source file missing: {path}")
        raw[layer] = read_csv(path)
        provenance[layer] = source_metadata(path, relative_path, len(raw[layer]))

    city_rows: dict[str, dict[str, list[dict[str, str]]]] = {
        city_id: {layer: [] for layer in SOURCE_FILES} for city_id in TARGET_CITIES
    }
    rejected_aliases: dict[str, Counter[str]] = {layer: Counter() for layer in SOURCE_FILES}
    for layer, rows in raw.items():
        for row in rows:
            city_id = normalize_city(row.get("city"))
            if city_id in city_rows:
                enriched = dict(row)
                enriched["canonical_city_id"] = city_id
                city_rows[city_id][layer].append(enriched)
            else:
                rejected_aliases[layer][clean(row.get("city")) or "(blank)"] += 1

    # Avoid a wall-clock value so identical admitted inputs rebuild byte-for-byte.
    generated_at = max(
        datetime.fromtimestamp((data_root / path).stat().st_mtime, tz=timezone.utc)
        for path in SOURCE_FILES.values()
    ).replace(microsecond=0).isoformat()
    city_catalog = []
    city_comparison = []
    city_details: dict[str, dict[str, Any]] = {}
    city_hex_features: dict[str, list[dict[str, Any]]] = {}
    city_category_hex_features: dict[str, dict[str, list[dict[str, Any]]]] = {}
    city_artifacts: dict[str, dict[str, Any]] = {}
    hex_artifacts: dict[str, dict[str, Any]] = {}
    category_hex_artifacts: dict[str, dict[str, dict[str, Any]]] = {}
    for city_id in TARGET_CITIES:
        layers = city_rows[city_id]
        schools = layers["schools"]
        tiers_seen = Counter(clean(row.get("fee_tier")) for row in schools)
        invalid_tier_count = sum(count for tier, count in tiers_seen.items() if tier not in TIERS)
        ids = Counter(clean(row.get("school_id")) for row in schools if clean(row.get("school_id")))
        udise = Counter(clean(row.get("udise_code")) for row in schools if clean(row.get("udise_code")))
        categories = category_metrics(schools, city_id)
        context = {
            layer: layer_summary(layers[layer], layer, city_id)
            for layer in ("projects", "hospitals", "localities", "offices")
        }
        quality_flags = []
        if invalid_tier_count:
            quality_flags.append("invalid_fee_tier_records")
        if any(count > 1 for count in ids.values()):
            quality_flags.append("duplicate_school_ids")
        if any(count > 1 for count in udise.values()):
            quality_flags.append("duplicate_udise_codes")
        if (categories["all_private"]["coverage"]["verified_coordinate_pct"] or 0) < 50:
            quality_flags.append("majority_school_coordinates_not_google_verified")
        if (categories["all_private"]["coverage"]["estimated_grade_2_9_share_pct"] or 0) > 0:
            quality_flags.append("contains_modeled_enrollment")

        map_geometry = city_map_geometry(layers, city_id)
        summary = {
            "canonical_city_id": city_id,
            "city_label": CITY_LABELS[city_id],
            "schema_version": SCHEMA_VERSION,
            "methodology_version": METHODOLOGY_VERSION,
            "map": map_geometry,
            "category_metrics": categories,
            "context_layers": context,
            "quality": {
                "status": "warning" if quality_flags else "qualified",
                "flags": quality_flags,
                "invalid_fee_tier_record_count": invalid_tier_count,
                "duplicate_school_id_count": sum(1 for count in ids.values() if count > 1),
                "duplicate_udise_code_count": sum(1 for count in udise.values() if count > 1),
                "fee_tier_counts": {tier: tiers_seen[tier] for tier in TIERS},
            },
        }
        summary["quality"]["warnings"] = quality_warnings(summary)

        districts = aggregate_school_geography(
            schools, lambda row: row.get("district"), city_id=city_id
        )
        pincodes = aggregate_school_geography(
            schools, lambda row: row.get("pincode"), city_id=city_id
        )
        localities = aggregate_school_geography(
            schools,
            lambda row: row.get("area") or row.get("district") or row.get("pincode"),
            city_id=city_id,
        )
        h3_cells = aggregate_school_geography(
            schools,
            lambda row: h3_cell(row, city_id=city_id),
            city_id=city_id,
        )
        spatial_concentration = {}
        for category_id in CATEGORIES:
            cell_students = sorted(
                (
                    cell["category_metrics"][category_id]["reported_students_grade_2_9"]
                    for cell in h3_cells
                    if (cell["category_metrics"][category_id]["reported_students_grade_2_9"] or 0) > 0
                ),
                reverse=True,
            )
            mapped_students = sum(cell_students)
            spatial_concentration[category_id] = {
                "mapped_students_grade_2_9": mapped_students,
                "mapped_student_coverage_pct": (
                    pct(mapped_students, categories[category_id]["reported_students_grade_2_9"])
                    if categories[category_id]["reported_students_grade_2_9"] is not None else None
                ),
                "occupied_h3_res7_cells": len(cell_students),
                "top_10_h3_student_share_pct": pct(sum(cell_students[:10]), mapped_students),
                "student_hhi_across_h3": (
                    round(sum((value / mapped_students) ** 2 for value in cell_students), 6)
                    if mapped_students else None
                ),
            }
        summary["spatial_concentration"] = spatial_concentration
        components = []
        if city_id == "delhi_ncr":
            components = aggregate_school_geography(
                schools,
                delhi_component,
                lambda key, _group: {
                    "delhi": "Delhi", "gurugram": "Gurugram", "faridabad": "Faridabad",
                    "noida_greater_noida": "Noida / Greater Noida", "ghaziabad": "Ghaziabad",
                    "hapur": "Hapur", "palwal": "Palwal", "bulandshahr": "Bulandshahr",
                    "meerut": "Meerut", "unassigned": "Unassigned",
                }.get(key, key),
                city_id=city_id,
            )

        features, by_category = build_h3_features(city_id, layers)
        feature_by_hex = {feature["properties"]["hex_id"]: feature["properties"] for feature in features}
        for cell in h3_cells:
            feature_props = feature_by_hex.get(cell["id"])
            if feature_props:
                cell["label"] = feature_props["neighborhood_name"]
                cell["neighborhood_name_source"] = feature_props["neighborhood_name_source"]
                cell["neighborhood_name_confidence"] = feature_props["neighborhood_name_confidence"]
                cell["neighborhood_name_distance_km"] = feature_props["neighborhood_name_distance_km"]
                cell["context"] = feature_props["context"]
                cell["category_scores"] = feature_props["category_scores"]
                cell["primary_score"] = feature_props["primary_score"]
        city_hex_features[city_id] = features
        city_category_hex_features[city_id] = by_category
        detail = {
            **summary,
            "geographies": {
                "delhi_ncr_components": components,
                "districts": districts,
                "pincodes": pincodes,
                "localities": localities,
                "h3_resolution": 7,
                "h3_cells": h3_cells,
            },
            "map_artifacts": {
                "all_hexes_path": f"hexes/{city_id}.geojson",
                "category_hexes_path_template": f"hexes/{city_id}__{{category_id}}.geojson",
            },
        }
        detail["decision_support"] = build_decision_support(
            city_id,
            layers,
            by_category["premium_plus"],
        )
        city_details[city_id] = detail
        city_comparison.append(summary)
        city_catalog.append({
            "canonical_city_id": city_id,
            "label": CITY_LABELS[city_id],
            "detail_path": f"cities/{city_id}.json",
            "hexes_path": f"hexes/{city_id}.geojson",
            "category_hexes_path_template": f"hexes/{city_id}__{{category_id}}.geojson",
            "map": map_geometry,
            "is_current_market_benchmark": city_id == "delhi_ncr",
        })

    scores = build_scores(city_comparison)
    for summary in city_comparison:
        city_id = summary["canonical_city_id"]
        summary["expansion_scores"] = scores[city_id]
        city_details[city_id]["expansion_scores"] = scores[city_id]
        city_details[city_id]["local_insights"] = city_local_insights(
            city_id,
            city_details[city_id],
            city_category_hex_features[city_id],
        )

    score_payload = {
        "schema_version": SCHEMA_VERSION,
        "methodology_version": METHODOLOGY_VERSION,
        "generated_at": generated_at,
        "model": {
            "id": "school_led_expansion_fit_v2",
            "label": "School-led expansion fit",
            "weights": SCORING_WEIGHTS,
            "hex_metric_normalization": "log_p5_p95_by_city_category_for_h3_metrics",
            "benchmark_city_id": "delhi_ncr",
            "ranked_candidate_city_ids": [city_id for city_id in TARGET_CITIES if city_id != "delhi_ncr"],
            "notes": [
                "Source-reported all-grade enrollment is the primary city-ranking evidence; modeled enrollment is excluded.",
                "Grades 2-9 for reporting schools are a transparent derivation used only for campus scenarios and local comparisons.",
                "Delhi NCR is shown as the current-market benchmark and is not ranked as the next city.",
                "Missing score components are reweighted across known components and surfaced through warnings.",
                "H3 map scores use robust log-percentile normalization within each city/category to avoid one extreme cell flattening the rest of the city.",
            ],
        },
        "categories": {
            category_id: {
                "category_id": category_id,
                "cities": [
                    {
                        "canonical_city_id": row["canonical_city_id"],
                        "city_label": row["city_label"],
                        **scores[row["canonical_city_id"]][category_id],
                    }
                    for row in sorted(
                        city_comparison,
                        key=lambda item: (
                            item["canonical_city_id"] == "delhi_ncr",
                            scores[item["canonical_city_id"]][category_id].get("candidate_rank") or 999,
                            item["canonical_city_id"],
                        ),
                    )
                ],
            }
            for category_id in CATEGORIES
        },
    }

    city_layer_payload = {
        "type": "FeatureCollection",
        "schema_version": SCHEMA_VERSION,
        "methodology_version": METHODOLOGY_VERSION,
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [
                        item["map"]["center"]["longitude"],
                        item["map"]["center"]["latitude"],
                    ],
                },
                "properties": {
                    "canonical_city_id": item["canonical_city_id"],
                    "city_label": item["city_label"],
                    "is_current_market_benchmark": item["canonical_city_id"] == "delhi_ncr",
                    "map": item["map"],
                    "expansion_scores": scores[item["canonical_city_id"]],
                    "quality": item["quality"],
                },
            }
            for item in city_comparison
        ],
    }

    for city_id in TARGET_CITIES:
        city_path = output_root / "cities" / f"{city_id}.json"
        write_json(city_path, city_details[city_id])
        city_artifacts[city_id] = artifact_metadata(city_path, output_root)

        hex_path = output_root / "hexes" / f"{city_id}.geojson"
        write_json(hex_path, {
            "type": "FeatureCollection",
            "schema_version": SCHEMA_VERSION,
            "methodology_version": METHODOLOGY_VERSION,
            "canonical_city_id": city_id,
            "features": city_hex_features[city_id],
        })
        hex_artifacts[city_id] = artifact_metadata(hex_path, output_root)

        category_hex_artifacts[city_id] = {}
        for category_id in CATEGORIES:
            category_hex_path = output_root / "hexes" / f"{city_id}__{category_id}.geojson"
            write_json(category_hex_path, {
                "type": "FeatureCollection",
                "schema_version": SCHEMA_VERSION,
                "methodology_version": METHODOLOGY_VERSION,
                "canonical_city_id": city_id,
                "category_id": category_id,
                "features": city_category_hex_features[city_id][category_id],
            })
            category_hex_artifacts[city_id][category_id] = artifact_metadata(category_hex_path, output_root)

    comparison_payload = {
        "schema_version": SCHEMA_VERSION,
        "methodology_version": METHODOLOGY_VERSION,
        "generated_at": generated_at,
        "cities": city_comparison,
    }
    comparison_path = output_root / "city_comparison.json"
    write_json(comparison_path, comparison_payload)
    score_path = output_root / "score_model.json"
    write_json(score_path, score_payload)
    city_layer_path = output_root / "india_cities.geojson"
    write_json(city_layer_path, city_layer_payload)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "methodology_version": METHODOLOGY_VERSION,
        "generated_at": generated_at,
        "city_comparison_path": "city_comparison.json",
        "score_model_path": "score_model.json",
        "city_layer_path": "india_cities.geojson",
        "map_defaults": {
            "center": {"latitude": 22.9734, "longitude": 78.6569},
            "zoom": 5,
            "selectable_city_ids": list(TARGET_CITIES),
            "benchmark_city_id": "delhi_ncr",
        },
        "scoring_model": {
            "id": "school_led_expansion_fit_v2",
            "label": "School-led expansion fit",
            "weights": SCORING_WEIGHTS,
            "hex_metric_normalization": "log_p5_p95_by_city_category_for_h3_metrics",
            "benchmark_city_id": "delhi_ncr",
            "ranked_candidate_city_ids": [city_id for city_id in TARGET_CITIES if city_id != "delhi_ncr"],
        },
        "artifacts": {
            "comparison": artifact_metadata(comparison_path, output_root),
            "score": artifact_metadata(score_path, output_root),
            "city_layer": artifact_metadata(city_layer_path, output_root),
            "cities": city_artifacts,
            "hexes": hex_artifacts,
            "category_hexes": category_hex_artifacts,
        },
        "cities": city_catalog,
        "categories": [
            {"id": category_id, **definition, "kind": "single_tier" if len(definition["tiers"]) == 1 else "rollup"}
            for category_id, definition in CATEGORIES.items()
        ],
        "constraints": {
            "custom_annual_fee_filter_supported": False,
            "reason": "The supplied school source contains fee_tier labels but no comparable annual fee values.",
            "primary_student_scope": "source-reported all-grade enrollment in selected school tiers",
            "derived_student_scope": "Grades 2-9 derived for source-reported schools",
            "modeled_enrollment_in_primary_rankings": False,
            "campus_scenario_capture_rates": [0.01, 0.02, 0.03],
            "campus_scenario_seats_per_campus": 200,
            "campus_scenario_target_utilization": 0.8,
            "source_observation_as_of": None,
            "academic_year": None,
        },
        "source_provenance": provenance,
        "excluded_source_city_labels": {
            layer: dict(sorted(counter.items())) for layer, counter in rejected_aliases.items()
        },
    }
    write_json(output_root / "manifest.json", manifest)

    # Vercel serves ``public`` as protected static content and deliberately does
    # not copy that directory into Python function bundles.  Keep the compact
    # API index artifacts beside the function source; large city and H3 payloads
    # continue to be served from the authenticated static data route.
    default_output_root = Path(__file__).resolve().parent / "public" / "data" / "multicity"
    if output_root.resolve() == default_output_root.resolve():
        runtime_root = Path(__file__).resolve().parent / "runtime_data" / "multicity"
        runtime_root.mkdir(parents=True, exist_ok=True)
        for artifact_name in ("manifest.json", "city_comparison.json", "score_model.json"):
            shutil.copy2(output_root / artifact_name, runtime_root / artifact_name)

    print(f"Built {len(city_catalog)} cities in {output_root}")
    for city in city_comparison:
        metric = city["category_metrics"]["all_private"]
        premium = city["category_metrics"]["premium_plus"]
        print(
            f"{city['city_label']}: {metric['school_count']:,} schools; "
            f"{metric['reported_enrollment_total'] or 0:,} source-reported students; "
            f"{premium['reported_enrollment_total'] or 0:,} Premium+"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "final_data" / "multicity_source",
        help="Directory containing the supplied Final Data folders",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(__file__).resolve().parent / "public" / "data" / "multicity",
        help="Artifact output directory",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    build(args.data_root.resolve(), args.output_root.resolve())
