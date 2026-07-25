#!/usr/bin/env python3
"""
Bulk geocode the school dataset with Google Places / Geocoding APIs.

The script:
- audits the source rows first
- geocodes each listing with Google Places text search
- falls back to Geocoding API when Places search is inconclusive
- preserves original coordinates in source_lat/source_lon
- refreshes lat/lon, hex_id, zone, address, and pincode when a better Google
  match is found
- writes a geocoded dataset plus an audit report
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import math
import os
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import h3
import requests


WORKSPACE_DIR = Path(__file__).resolve().parent.parent
INPUT_PATH = WORKSPACE_DIR / "new data" / "schools.json"
OUTPUT_PATH = WORKSPACE_DIR / "new data" / "schools_geocoded.json"
PUBLIC_OUTPUT_PATH = WORKSPACE_DIR / "src" / "public" / "data" / "schools.json"
REPORT_PATH = WORKSPACE_DIR / "src" / "public" / "reports" / "schools_audit_report.json"

GOOGLE_PLACES_TEXT_URL = "https://places.googleapis.com/v1/places:searchText"
GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

CENTRAL_LAT = 12.9716
CENTRAL_LON = 77.5946
BENGALURU_BOUNDS = {
    "min_lat": 12.45,
    "max_lat": 13.50,
    "min_lon": 77.10,
    "max_lon": 78.10,
}


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokens(text: str) -> set[str]:
    stopwords = {
        "school",
        "schools",
        "international",
        "academy",
        "academies",
        "public",
        "bengaluru",
        "bangalore",
        "residential",
        "junior",
        "college",
        "prep",
        "pre",
        "primary",
        "the",
        "and",
    }
    return {tok for tok in clean_text(text).split() if tok and tok not in stopwords}


def token_similarity(a: str, b: str) -> float:
    ta = tokens(a)
    tb = tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    if None in (lat1, lon1, lat2, lon2):
        return float("inf")
    r = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bearing_degrees(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlam = math.radians(lon2 - lon1)
    x = math.sin(dlam) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def classify_zone(lat: float, lon: float) -> str:
    distance = haversine_m(CENTRAL_LAT, CENTRAL_LON, lat, lon) / 1000.0
    if distance > 35.0:
        return "Outside"
    if distance <= 5.0:
        return "Central"
    brng = bearing_degrees(CENTRAL_LAT, CENTRAL_LON, lat, lon)
    if brng >= 337.5 or brng < 22.5:
        return "North"
    if 22.5 <= brng < 67.5:
        return "North-East"
    if 67.5 <= brng < 112.5:
        return "East"
    if 112.5 <= brng < 157.5:
        return "South-East"
    if 157.5 <= brng < 202.5:
        return "South"
    if 202.5 <= brng < 247.5:
        return "South-West"
    if 247.5 <= brng < 292.5:
        return "West"
    if 292.5 <= brng < 337.5:
        return "North-West"
    return "Unknown"


def valid_lat_lon(lat: Any, lon: Any) -> bool:
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except Exception:
        return False
    return (
        BENGALURU_BOUNDS["min_lat"] <= lat_f <= BENGALURU_BOUNDS["max_lat"]
        and BENGALURU_BOUNDS["min_lon"] <= lon_f <= BENGALURU_BOUNDS["max_lon"]
    )


def as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except Exception:
            return None
    return None


def build_query_variants(row: dict[str, Any]) -> list[str]:
    name = row.get("name")
    area = row.get("area")
    address = row.get("address")
    pincode = row.get("pincode")
    alias_name = re.sub(r"\s*-\s*residential\b.*$", "", str(name), flags=re.IGNORECASE).strip()
    alias_name = re.sub(r"\s*\(.*\)$", "", alias_name).strip()

    variants: list[list[Any]] = []
    base = [alias_name or name]
    if area and area != "Unknown":
        base.append(area)
    variants.append(base)

    if pincode and pincode != "NA":
        variants.append([alias_name or name, str(pincode)])

    if address and address != "NA":
        variants.append([alias_name or name, address])

    variants.append([alias_name or name, area, address, pincode])
    if alias_name and alias_name.lower() != str(name).lower():
        variants.append([name, area])
        if address and address != "NA":
            variants.append([name, address])

    rendered = []
    for parts in variants:
        cleaned = [str(part) for part in parts if part not in (None, "", "NA", "Unknown")]
        cleaned.extend(["Bangalore", "Karnataka", "India"])
        query = ", ".join(cleaned)
        if query not in rendered:
            rendered.append(query)
    return rendered


def get_google_key() -> str:
    api_key = (os.environ.get("GOOGLE_MAPS_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("GOOGLE_MAPS_API_KEY is required")
    return api_key


def request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    retries: int = 3,
    timeout: int = 20,
) -> dict[str, Any] | None:
    last_error = None
    for attempt in range(retries):
        try:
            response = session.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_body,
                timeout=timeout,
            )
            if response.status_code in {429, 500, 502, 503, 504}:
                last_error = RuntimeError(
                    f"{response.status_code}: {response.text[:200]}"
                )
                continue
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_error = exc
    if last_error:
        raise last_error
    return None


def extract_postal_code(address_components: Iterable[dict[str, Any]]) -> str | None:
    for component in address_components or []:
        types = component.get("types") or []
        if "postal_code" in types:
            return component.get("longText") or component.get("shortText")
    return None


def extract_locality(address_components: Iterable[dict[str, Any]]) -> str | None:
    preferred = [
        "sublocality_level_1",
        "sublocality",
        "locality",
        "neighborhood",
        "administrative_area_level_3",
    ]
    for wanted in preferred:
        for component in address_components or []:
            if wanted in (component.get("types") or []):
                return component.get("longText") or component.get("shortText")
    return None


def place_candidates(session: requests.Session, api_key: str, row: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": (
            "places.id,places.displayName,places.formattedAddress,"
            "places.location,places.types,places.addressComponents"
        ),
    }
    query_variants = build_query_variants(row)
    for query in query_variants:
        body = {
            "textQuery": query,
            "locationBias": {
                "circle": {
                    "center": {
                        "latitude": float(row["lat"]),
                        "longitude": float(row["lon"]),
                    },
                    "radius": 12000.0,
                }
            },
            "includedType": "school",
            "languageCode": "en-IN",
            "maxResultCount": 10,
        }
        payload = request_json(
            session,
            "POST",
            GOOGLE_PLACES_TEXT_URL,
            headers=headers,
            json_body=body,
        )
        places = payload.get("places", []) if payload else []
        if places:
            return places, query
    return [], query_variants[-1]


def geocode_candidates(session: requests.Session, api_key: str, row: dict[str, Any]) -> list[dict[str, Any]]:
    params = {
        "address": build_query(row),
        "bounds": f"{row['lat'] - 0.1},{row['lon'] - 0.1}|{row['lat'] + 0.1},{row['lon'] + 0.1}",
        "region": "in",
        "key": api_key,
    }
    payload = request_json(session, "GET", GOOGLE_GEOCODE_URL, params=params)
    if not payload or payload.get("status") not in {"OK", "ZERO_RESULTS"}:
        return []
    out = []
    for result in payload.get("results", []):
        loc = result.get("geometry", {}).get("location", {})
        out.append(
            {
                "id": result.get("place_id"),
                "displayName": {"text": result.get("formatted_address", "")},
                "formattedAddress": result.get("formatted_address"),
                "location": {
                    "latitude": loc.get("lat"),
                    "longitude": loc.get("lng"),
                },
                "types": result.get("types", []),
                "addressComponents": result.get("address_components", []),
                "_source": "geocoding_api",
            }
        )
    return out


def reverse_geocode(session: requests.Session, api_key: str, lat: float, lon: float) -> list[dict[str, Any]]:
    params = {
        "latlng": f"{lat},{lon}",
        "region": "in",
        "key": api_key,
    }
    payload = request_json(session, "GET", GOOGLE_GEOCODE_URL, params=params)
    if not payload or payload.get("status") not in {"OK", "ZERO_RESULTS"}:
        return []
    out = []
    for result in payload.get("results", []):
        loc = result.get("geometry", {}).get("location", {})
        out.append(
            {
                "id": result.get("place_id"),
                "displayName": {"text": result.get("formatted_address", "")},
                "formattedAddress": result.get("formatted_address"),
                "location": {
                    "latitude": loc.get("lat"),
                    "longitude": loc.get("lng"),
                },
                "types": result.get("types", []),
                "addressComponents": result.get("address_components", []),
                "_source": "reverse_geocoding_api",
            }
        )
    return out


def score_candidate(row: dict[str, Any], candidate: dict[str, Any]) -> tuple[float, float, float]:
    location = candidate.get("location") or {}
    cand_lat = as_float(location.get("latitude"))
    cand_lon = as_float(location.get("longitude"))
    dist_m = haversine_m(row["lat"], row["lon"], cand_lat, cand_lon)
    cand_name = ""
    display = candidate.get("displayName") or {}
    if isinstance(display, dict):
        cand_name = display.get("text") or ""
    name_score = token_similarity(row.get("name", ""), cand_name)
    type_bonus = 0.0
    candidate_types = candidate.get("types") or []
    if any(
        t in candidate_types
        for t in (
            "school",
            "educational_institution",
            "preschool",
            "primary_school",
            "secondary_school",
            "kindergarten",
            "university",
            "college",
            "higher_education",
        )
    ):
        type_bonus = 0.35
    elif any(t in candidate_types for t in ("establishment", "point_of_interest")):
        type_bonus = 0.15
    dist_bonus = max(0.0, 1.0 - min(dist_m / 15000.0, 1.0))
    score = name_score * 2.0 + dist_bonus + type_bonus
    return score, dist_m, name_score


@dataclass
class GeocodeResult:
    status: str
    used_query: str
    google_place_id: str | None
    google_formatted_address: str | None
    google_types: list[str]
    google_lat: float | None
    google_lon: float | None
    google_locality: str | None
    google_postal_code: str | None
    geocode_confidence: float
    geocode_distance_m: float | None
    geocoded: bool
    geocode_source: str


def enrich_row(session: requests.Session, api_key: str, row: dict[str, Any]) -> tuple[dict[str, Any], GeocodeResult]:
    original_lat = float(row["lat"])
    original_lon = float(row["lon"])
    query = build_query_variants(row)[0]

    candidates = []
    source = "places_text_search"
    try:
        candidates, query = place_candidates(session, api_key, row)
    except Exception:
        candidates = []

    if not candidates:
        source = "geocoding_api"
        try:
            candidates = geocode_candidates(session, api_key, row)
        except Exception:
            candidates = []

    best = None
    best_score = -1.0
    best_dist = None
    best_name_score = 0.0
    for candidate in candidates:
        score, dist_m, name_score = score_candidate(row, candidate)
        if score > best_score:
            best = candidate
            best_score = score
            best_dist = dist_m
            best_name_score = name_score

    geocoded = best is not None
    google_lat = original_lat
    google_lon = original_lon
    google_place_id = None
    google_address = None
    google_types: list[str] = []
    google_locality = None
    google_postal_code = None
    geocode_distance_m = 0.0
    confidence = 0.35
    status = "fallback_source_coords"
    geocode_source = "source_coords"

    if best:
        location = best.get("location") or {}
        candidate_lat = as_float(location.get("latitude"))
        candidate_lon = as_float(location.get("longitude"))
        candidate_in_bounds = candidate_lat is not None and candidate_lon is not None and valid_lat_lon(candidate_lat, candidate_lon)
        if candidate_lat is not None and candidate_lon is not None and candidate_in_bounds:
            google_lat = candidate_lat
            google_lon = candidate_lon
            geocode_distance_m = haversine_m(original_lat, original_lon, google_lat, google_lon)
        google_place_id = best.get("id")
        google_address = best.get("formattedAddress")
        google_types = list(best.get("types") or [])
        components = best.get("addressComponents") or []
        google_locality = extract_locality(components)
        google_postal_code = extract_postal_code(components)

        if geocode_distance_m is None:
            geocode_distance_m = 0.0
        if candidate_in_bounds and any(
            t in google_types
            for t in (
                "school",
                "educational_institution",
                "preschool",
                "primary_school",
                "secondary_school",
                "kindergarten",
                "university",
                "college",
                "higher_education",
            )
        ):
            status = "google_match"
            geocode_source = source
            if best_name_score >= 0.7:
                confidence = 0.98
            elif best_name_score >= 0.45:
                confidence = 0.92
            elif best_name_score >= 0.25:
                confidence = 0.84
            else:
                confidence = 0.75
        else:
            status = "google_weak_match"
            geocode_source = source
            confidence = 0.6 if best_name_score >= 0.35 else 0.5
    else:
        try:
            reverse = reverse_geocode(session, api_key, original_lat, original_lon)
        except Exception:
            reverse = []
        if reverse:
            best = reverse[0]
            location = best.get("location") or {}
            candidate_lat = as_float(location.get("latitude"))
            candidate_lon = as_float(location.get("longitude"))
            if candidate_lat is not None and candidate_lon is not None:
                google_lat = candidate_lat
                google_lon = candidate_lon
                geocode_distance_m = 0.0
            google_place_id = best.get("id")
            google_address = best.get("formattedAddress")
            google_types = list(best.get("types") or [])
            components = best.get("addressComponents") or []
            google_locality = extract_locality(components)
            google_postal_code = extract_postal_code(components)
            status = "reverse_geocoded_source"
            geocode_source = "reverse_geocoding_api"
            confidence = 0.68 if valid_lat_lon(original_lat, original_lon) else 0.55

    updated = dict(row)
    updated["source_lat"] = original_lat
    updated["source_lon"] = original_lon
    updated["google_place_id"] = google_place_id
    updated["google_formatted_address"] = google_address
    updated["google_types"] = google_types
    updated["google_geocode_query"] = query
    updated["google_geocode_source"] = geocode_source
    updated["google_geocode_confidence"] = round(confidence, 3)
    updated["google_geocode_distance_m"] = round(geocode_distance_m, 1) if geocoded else None
    updated["google_locality"] = google_locality
    updated["google_postal_code"] = google_postal_code

    if geocoded and status == "google_match":
        updated["lat"] = google_lat
        updated["lon"] = google_lon
        if google_address and updated.get("address") in (None, "", "NA"):
            updated["address"] = google_address
        if google_postal_code and updated.get("pincode") in (None, "", "NA"):
            try:
                updated["pincode"] = int(google_postal_code)
            except Exception:
                updated["pincode"] = google_postal_code
        if google_locality and updated.get("area") in (None, "", "Unknown"):
            updated["area"] = google_locality
    else:
        updated["lat"] = original_lat
        updated["lon"] = original_lon

    if updated.get("address") == "NA" and google_address:
        updated["address"] = google_address
    if updated.get("pincode") == "NA" and google_postal_code:
        try:
            updated["pincode"] = int(google_postal_code)
        except Exception:
            updated["pincode"] = google_postal_code

    result = GeocodeResult(
        status=status,
        used_query=query,
        google_place_id=google_place_id,
        google_formatted_address=google_address,
        google_types=google_types,
        google_lat=google_lat,
        google_lon=google_lon,
        google_locality=google_locality,
        google_postal_code=google_postal_code,
        geocode_confidence=round(confidence, 3),
        geocode_distance_m=round(geocode_distance_m, 1) if geocoded else None,
        geocoded=geocoded,
        geocode_source=geocode_source,
    )
    return updated, result


def profile_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    name_counts = Counter(row.get("name") for row in rows)
    normalized_counts = Counter(clean_text(row.get("name")) for row in rows)
    coord_counts = Counter((round(row["lat"], 6), round(row["lon"], 6)) for row in rows)

    def placeholder_count(field: str, placeholder: Any) -> int:
        return sum(1 for row in rows if row.get(field) == placeholder)

    students_total = [as_float(row.get("students_total")) for row in rows if as_float(row.get("students_total")) is not None]
    students = [as_float(row.get("students")) for row in rows if as_float(row.get("students")) is not None]
    fees = [as_float(row.get("fee")) for row in rows if as_float(row.get("fee")) is not None]

    return {
        "record_count": len(rows),
        "exact_duplicate_names": sum(1 for c in name_counts.values() if c > 1),
        "normalized_duplicate_names": sum(1 for c in normalized_counts.values() if c > 1),
        "duplicate_coordinate_points": sum(1 for c in coord_counts.values() if c > 1),
        "rows_with_na_address": placeholder_count("address", "NA"),
        "rows_with_na_pincode": placeholder_count("pincode", "NA"),
        "rows_with_unknown_area": placeholder_count("area", "Unknown"),
        "rows_missing_udise_code": sum(1 for row in rows if row.get("udise_code") in (None, "", "NA")),
        "rows_missing_hex_id": sum(1 for row in rows if row.get("hex_id") in (None, "")),
        "rows_missing_zone": sum(1 for row in rows if row.get("zone") in (None, "")),
        "rows_missing_fee_bracket_min": sum(1 for row in rows if row.get("fee_bracket_min") is None),
        "rows_missing_fee_bracket_max": sum(1 for row in rows if row.get("fee_bracket_max") is None),
        "rows_missing_rank_in_bracket": sum(1 for row in rows if row.get("rank_in_bracket") is None),
        "students_total_max": max(students_total) if students_total else None,
        "students_max": max(students) if students else None,
        "fee_max": max(fees) if fees else None,
    }


def summarize_audit(rows: list[dict[str, Any]], geocode_results: list[GeocodeResult]) -> dict[str, Any]:
    source_profile = profile_rows(rows)
    geocoded_rows = sum(1 for result in geocode_results if result.status == "google_match")
    weak_rows = sum(1 for result in geocode_results if result.status == "google_weak_match")
    fallback_rows = sum(1 for result in geocode_results if result.status == "fallback_source_coords")
    confidence_values = [result.geocode_confidence for result in geocode_results]
    distances = [result.geocode_distance_m for result in geocode_results if result.geocode_distance_m is not None]

    by_status = Counter(result.status for result in geocode_results)

    high_distance = []
    for row, result in zip(rows, geocode_results):
        if result.geocode_distance_m is not None and result.geocode_distance_m >= 2500:
            high_distance.append(
                {
                    "name": row.get("name"),
                    "area": row.get("area"),
                    "source_lat": row.get("lat"),
                    "source_lon": row.get("lon"),
                    "google_lat": result.google_lat,
                    "google_lon": result.google_lon,
                    "distance_m": result.geocode_distance_m,
                    "query": result.used_query,
                    "confidence": result.geocode_confidence,
                    "status": result.status,
                }
            )

    low_confidence = []
    for row, result in zip(rows, geocode_results):
        if result.geocode_confidence < 0.8:
            low_confidence.append(
                {
                    "name": row.get("name"),
                    "area": row.get("area"),
                    "confidence": result.geocode_confidence,
                    "status": result.status,
                    "query": result.used_query,
                }
            )

    duplicate_examples = []
    name_counts = Counter(clean_text(row.get("name")) for row in rows)
    repeated = [name for name, count in name_counts.items() if count > 1]
    for norm_name in sorted(repeated, key=lambda n: (-name_counts[n], n))[:20]:
        duplicate_examples.append(
            {
                "normalized_name": norm_name,
                "count": name_counts[norm_name],
                "examples": [
                    {
                        "name": row.get("name"),
                        "area": row.get("area"),
                        "address": row.get("address"),
                    }
                    for row in rows
                    if clean_text(row.get("name")) == norm_name
                ][:5],
            }
        )

    return {
        "source_profile": source_profile,
        "geocode_summary": {
            "google_match": geocoded_rows,
            "google_weak_match": weak_rows,
            "fallback_source_coords": fallback_rows,
            "status_breakdown": dict(by_status),
            "confidence_min": min(confidence_values) if confidence_values else None,
            "confidence_median": statistics.median(confidence_values) if confidence_values else None,
            "confidence_mean": round(statistics.mean(confidence_values), 3) if confidence_values else None,
            "distance_median_m": statistics.median(distances) if distances else None,
            "distance_mean_m": round(statistics.mean(distances), 1) if distances else None,
        },
        "quality_flags": {
            "rows_with_distance_over_2500m": len(high_distance),
            "rows_with_confidence_below_0_8": len(low_confidence),
        },
        "high_distance_examples": high_distance[:50],
        "low_confidence_examples": low_confidence[:50],
        "duplicate_name_examples": duplicate_examples,
    }


def main() -> None:
    api_key = get_google_key()
    if not INPUT_PATH.exists():
        raise FileNotFoundError(f"Input file not found: {INPUT_PATH}")

    rows = json.loads(INPUT_PATH.read_text())
    if not isinstance(rows, list):
        raise TypeError("schools.json must contain a list of records")

    print(f"Loaded {len(rows)} school rows from {INPUT_PATH}")
    audit_before = profile_rows(rows)
    print("Pre-geocode audit:")
    for key, value in audit_before.items():
        print(f"  {key}: {value}")

    geocode_results: list[GeocodeResult] = [None] * len(rows)  # type: ignore[list-item]
    enriched_rows: list[dict[str, Any]] = [None] * len(rows)  # type: ignore[list-item]

    def worker(idx: int, row: dict[str, Any]) -> tuple[int, dict[str, Any], GeocodeResult]:
        session = requests.Session()
        enriched, result = enrich_row(session, api_key, row)
        return idx, enriched, result

    print("\nStarting Google enrichment...")
    completed = 0
    with cf.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, idx, row) for idx, row in enumerate(rows)]
        for future in cf.as_completed(futures):
            idx, enriched, result = future.result()
            enriched_rows[idx] = enriched
            geocode_results[idx] = result
            completed += 1
            if completed % 100 == 0 or completed == len(rows):
                print(f"  processed {completed}/{len(rows)}")

    report = summarize_audit(rows, geocode_results)
    report["input_path"] = str(INPUT_PATH)
    report["output_path"] = str(OUTPUT_PATH)
    report["public_output_path"] = str(PUBLIC_OUTPUT_PATH)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    OUTPUT_PATH.write_text(json.dumps(enriched_rows, indent=2, ensure_ascii=False))
    PUBLIC_OUTPUT_PATH.write_text(json.dumps(enriched_rows, indent=2, ensure_ascii=False))
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    status_counts = Counter(result.status for result in geocode_results)
    print("\nGeocode status counts:")
    for key, value in sorted(status_counts.items()):
        print(f"  {key}: {value}")
    print(f"\nWrote geocoded schools to {OUTPUT_PATH}")
    print(f"Wrote public schools data to {PUBLIC_OUTPUT_PATH}")
    print(f"Wrote audit report to {REPORT_PATH}")


if __name__ == "__main__":
    main()
