#!/usr/bin/env python3
"""
Bulk geocode Bangalore residential projects with Google Maps APIs.

This script preserves the source coordinates, enriches each project with
Google place metadata, computes hex/zone from the final coordinates, and
writes both a geocoded copy plus an audit report.
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import math
import os
import re
import statistics
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import h3
import requests


WORKSPACE_DIR = Path(__file__).resolve().parent.parent
INPUT_PATH = WORKSPACE_DIR / "new data" / "bangalore_projects_classified.json"
OUTPUT_PATH = WORKSPACE_DIR / "new data" / "bangalore_projects_geocoded.json"
REPORT_PATH = WORKSPACE_DIR / "src" / "public" / "reports" / "bangalore_projects_geocode_audit.json"

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
        "by",
        "the",
        "and",
        "of",
        "apartment",
        "apartments",
        "project",
        "projects",
        "residence",
        "residences",
        "residential",
        "bangalore",
        "bengaluru",
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


def query_variants(row: dict[str, Any]) -> list[str]:
    name = row.get("name")
    locality = row.get("locality")
    address_bits = [name, locality, row.get("category")]
    variants = []

    def add(parts: list[Any]) -> None:
        cleaned = [str(part) for part in parts if part not in (None, "", "NA", "Unknown")]
        cleaned.extend(["Bangalore", "Karnataka", "India"])
        query = ", ".join(cleaned)
        if query not in variants:
            variants.append(query)

    add([name, locality])
    add([name, locality, row.get("category")])
    add([name, row.get("category")])
    add([name, row.get("max_price") or row.get("min_price")])
    add(address_bits)
    return variants


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
    for _ in range(retries):
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
                last_error = RuntimeError(f"{response.status_code}: {response.text[:200]}")
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
        if "postal_code" in (component.get("types") or []):
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
    for query in query_variants(row):
        body = {
            "textQuery": query,
            "locationBias": {
                "circle": {
                    "center": {
                        "latitude": float(row["lat"]),
                        "longitude": float(row["lon"]),
                    },
                    "radius": 14000.0,
                }
            },
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
    return [], query_variants(row)[0]


def reverse_geocode(session: requests.Session, api_key: str, lat: float, lon: float) -> list[dict[str, Any]]:
    params = {"latlng": f"{lat},{lon}", "region": "in", "key": api_key}
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
                "location": {"latitude": loc.get("lat"), "longitude": loc.get("lng")},
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
    display = candidate.get("displayName") or {}
    cand_name = display.get("text") if isinstance(display, dict) else ""
    name_score = token_similarity(row.get("name", ""), cand_name or "")
    type_bonus = 0.0
    candidate_types = candidate.get("types") or []
    if any(
        t in candidate_types
        for t in (
            "apartment_complex",
            "apartment_building",
            "condominium_complex",
            "housing_complex",
            "residential_complex",
            "real_estate_agency",
            "point_of_interest",
            "service",
            "establishment",
        )
    ):
        type_bonus = 0.35
    dist_bonus = max(0.0, 1.0 - min(dist_m / 18000.0, 1.0))
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
    google_geocode_confidence: float
    google_geocode_distance_m: float | None
    google_geocode_source: str


def enrich_row(session: requests.Session, api_key: str, row: dict[str, Any]) -> tuple[dict[str, Any], GeocodeResult]:
    source_lat = float(row["lat"])
    source_lon = float(row["lon"])
    query = query_variants(row)[0]

    try:
        candidates, query = place_candidates(session, api_key, row)
    except Exception:
        candidates = []

    source = "places_text_search"
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

    google_lat = source_lat
    google_lon = source_lon
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
        cand_lat = as_float(location.get("latitude"))
        cand_lon = as_float(location.get("longitude"))
        if cand_lat is not None and cand_lon is not None:
            google_lat = cand_lat
            google_lon = cand_lon
            geocode_distance_m = haversine_m(source_lat, source_lon, google_lat, google_lon)
        google_place_id = best.get("id")
        google_address = best.get("formattedAddress")
        google_types = list(best.get("types") or [])
        google_locality = extract_locality(best.get("addressComponents") or [])
        google_postal_code = extract_postal_code(best.get("addressComponents") or [])
        if best_name_score >= 0.7:
            confidence = 0.98
        elif best_name_score >= 0.45:
            confidence = 0.92
        elif best_name_score >= 0.25:
            confidence = 0.84
        else:
            confidence = 0.75
        status = "google_match" if best_name_score >= 0.25 else "google_weak_match"
        geocode_source = source
    else:
        try:
            reverse = reverse_geocode(session, api_key, source_lat, source_lon)
        except Exception:
            reverse = []
        if reverse:
            best = reverse[0]
            google_place_id = best.get("id")
            google_address = best.get("formattedAddress")
            google_types = list(best.get("types") or [])
            google_locality = extract_locality(best.get("addressComponents") or [])
            google_postal_code = extract_postal_code(best.get("addressComponents") or [])
            confidence = 0.68
            status = "reverse_geocoded_source"
            geocode_source = "reverse_geocoding_api"

    updated = dict(row)
    updated["source_lat"] = source_lat
    updated["source_lon"] = source_lon
    updated["google_place_id"] = google_place_id
    updated["google_formatted_address"] = google_address
    updated["google_types"] = google_types
    updated["google_geocode_query"] = query
    updated["google_geocode_source"] = geocode_source
    updated["google_geocode_confidence"] = round(confidence, 3)
    updated["google_geocode_distance_m"] = round(geocode_distance_m, 1) if best else None
    updated["google_locality"] = google_locality
    updated["google_postal_code"] = google_postal_code

    if best and status == "google_match":
        updated["lat"] = google_lat
        updated["lon"] = google_lon

    if google_address and updated.get("address") in (None, "", "NA"):
        updated["address"] = google_address
    if google_postal_code and updated.get("pincode") in (None, "", "NA"):
        updated["pincode"] = google_postal_code
    if updated.get("pincode") in ("NA", "na"):
        updated["pincode"] = google_postal_code or updated.get("pincode")

    final_lat = as_float(updated.get("lat")) or source_lat
    final_lon = as_float(updated.get("lon")) or source_lon
    if valid_lat_lon(final_lat, final_lon):
        updated["hex_id"] = h3.latlng_to_cell(final_lat, final_lon, 7)
        updated["zone"] = classify_zone(final_lat, final_lon)

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
        google_geocode_confidence=round(confidence, 3),
        google_geocode_distance_m=round(geocode_distance_m, 1) if best else None,
        google_geocode_source=geocode_source,
    )
    return updated, result


def profile_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    names = Counter(r.get("name") for r in rows)
    coords = Counter((round(float(r["lat"]), 6), round(float(r["lon"]), 6)) for r in rows)
    price_sqft = [as_float(r.get("price_SQFT")) or 0.0 for r in rows]
    max_price = [as_float(r.get("max_price")) or 0.0 for r in rows]
    min_price = [as_float(r.get("min_price")) or 0.0 for r in rows]
    q1 = Counter(str(r.get("quartile analysis 1") or "") for r in rows)
    q2 = Counter(str(r.get("quartile analysis 2") or "") for r in rows)

    return {
        "record_count": len(rows),
        "duplicate_names": sum(1 for count in names.values() if count > 1),
        "duplicate_coordinate_points": sum(1 for count in coords.values() if count > 1),
        "missing_hex_id": sum(1 for r in rows if not str(r.get("hex_id") or "").strip()),
        "missing_price_sqft": sum(1 for r in rows if not as_float(r.get("price_SQFT"))),
        "min_price_gt_max_price": sum(1 for r in rows if (as_float(r.get("min_price")) or 0) > (as_float(r.get("max_price")) or 0)),
        "quartile_analysis_1": dict(q1),
        "quartile_analysis_2": dict(q2),
        "price_sqft_min": min(price_sqft) if price_sqft else None,
        "price_sqft_median": statistics.median(price_sqft) if price_sqft else None,
        "price_sqft_max": max(price_sqft) if price_sqft else None,
        "max_price_median": statistics.median(max_price) if max_price else None,
        "min_price_median": statistics.median(min_price) if min_price else None,
    }


def summarize_audit(rows: list[dict[str, Any]], results: list[GeocodeResult]) -> dict[str, Any]:
    counts = Counter(result.status for result in results)
    distances = [result.google_geocode_distance_m for result in results if result.google_geocode_distance_m is not None]
    confidences = [result.google_geocode_confidence for result in results]

    return {
        "source_profile": profile_rows(rows),
        "geocode_summary": {
            "google_match": counts.get("google_match", 0),
            "google_weak_match": counts.get("google_weak_match", 0),
            "reverse_geocoded_source": counts.get("reverse_geocoded_source", 0),
            "fallback_source_coords": counts.get("fallback_source_coords", 0),
            "status_breakdown": dict(counts),
            "confidence_min": min(confidences) if confidences else None,
            "confidence_median": statistics.median(confidences) if confidences else None,
            "confidence_mean": round(statistics.mean(confidences), 3) if confidences else None,
            "distance_median_m": statistics.median(distances) if distances else None,
            "distance_mean_m": round(statistics.mean(distances), 1) if distances else None,
        },
        "quality_flags": {
            "rows_with_distance_over_2500m": sum(
                1 for result in results if result.google_geocode_distance_m is not None and result.google_geocode_distance_m > 2500
            ),
            "rows_with_confidence_below_0_8": sum(1 for result in results if result.google_geocode_confidence < 0.8),
        },
    }


def main() -> None:
    api_key = get_google_key()
    if not INPUT_PATH.exists():
        raise FileNotFoundError(f"Input file not found: {INPUT_PATH}")

    rows = json.loads(INPUT_PATH.read_text())
    if not isinstance(rows, list):
        raise TypeError("Projects file must contain a list of records")

    print(f"Loaded {len(rows)} project rows from {INPUT_PATH}")
    before = profile_rows(rows)
    print("Pre-geocode audit:")
    for key, value in before.items():
        print(f"  {key}: {value}")

    enriched_rows: list[dict[str, Any]] = [None] * len(rows)  # type: ignore[list-item]
    geocode_results: list[GeocodeResult] = [None] * len(rows)  # type: ignore[list-item]

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

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(enriched_rows, indent=2, ensure_ascii=False))
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    print("\nGeocode status counts:")
    for key, value in sorted(Counter(r.status for r in geocode_results).items()):
        print(f"  {key}: {value}")
    print(f"\nWrote geocoded projects to {OUTPUT_PATH}")
    print(f"Wrote audit report to {REPORT_PATH}")


if __name__ == "__main__":
    main()
