#!/usr/bin/env python3
"""Free, cached society geocoding helper using OpenStreetMap Nominatim.

This utility is intentionally separate from the deterministic dashboard build.
Use it to refresh only suspicious/missing project coordinates, with a local
cache and a conservative one-request-per-second throttle.  It writes candidate
results for review; it does not overwrite source CSVs.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from build_multicity_platform import (
    CITY_LABELS,
    SOURCE_FILES,
    clean,
    in_city_window,
    normalize_city,
    number,
    project_coordinate_decision,
    source_pincode,
    sector_tokens,
    text_tokens,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = PROJECT_ROOT / "final_data" / "multicity_source"
DEFAULT_OUTPUT = Path("src/public/reports/free_society_geocode_candidates.csv")
DEFAULT_CACHE = Path("src/public/reports/free_society_geocode_cache.sqlite")
DEFAULT_OVERRIDES = Path("src/public/data/geocode_overrides/society_coordinates.json")
USER_AGENT = "rancho-multicity-validation/1.0 (local client analysis)"


def cache_get(conn: sqlite3.Connection, query: str) -> dict[str, Any] | None:
    conn.execute("CREATE TABLE IF NOT EXISTS geocode_cache (query TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at REAL NOT NULL)")
    row = conn.execute("SELECT payload FROM geocode_cache WHERE query = ?", (query,)).fetchone()
    return json.loads(row[0]) if row else None


def cache_put(conn: sqlite3.Connection, query: str, payload: dict[str, Any]) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO geocode_cache(query, payload, created_at) VALUES (?, ?, ?)",
        (query, json.dumps(payload, sort_keys=True), time.time()),
    )
    conn.commit()


def nominatim_geocode(conn: sqlite3.Connection, query: str, *, sleep_seconds: float) -> dict[str, Any]:
    cached = cache_get(conn, query)
    if cached is not None:
        return cached | {"cache_status": "hit"}
    time.sleep(sleep_seconds)
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({
        "q": query,
        "format": "jsonv2",
        "limit": 1,
        "countrycodes": "in",
        "addressdetails": 1,
    })
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        result = {
            "lat": None,
            "lon": None,
            "display_name": None,
            "type": None,
            "class": None,
            "importance": None,
            "error": str(exc),
            "raw": {},
        }
        cache_put(conn, query, result)
        return result | {"cache_status": "miss_error"}
    first = payload[0] if payload else {}
    result = {
        "lat": first.get("lat"),
        "lon": first.get("lon"),
        "display_name": first.get("display_name"),
        "type": first.get("type"),
        "class": first.get("class"),
        "importance": first.get("importance"),
        "raw": first,
    }
    cache_put(conn, query, result)
    return result | {"cache_status": "miss"}


def osm_candidate_is_accepted(row: dict[str, str], city_id: str, result: dict[str, Any]) -> tuple[bool, str]:
    lat, lon = number(result.get("lat")), number(result.get("lon"))
    if lat is None or lon is None:
        return False, "no_osm_result"
    if not in_city_window(city_id, lat, lon):
        return False, "outside_city_window"

    display = clean(result.get("display_name")).lower()
    if not display:
        return False, "blank_display_name"

    pin = source_pincode(row.get("pincode"))
    display_pin = source_pincode(display)
    if pin and display_pin and pin == display_pin:
        return True, "pincode_match"

    row_sectors = sector_tokens(row.get("locality"))
    if row_sectors and row_sectors & sector_tokens(display):
        return True, "sector_match"

    locality_tokens = text_tokens(row.get("locality"))
    display_tokens = text_tokens(display)
    if locality_tokens and len(locality_tokens & display_tokens) >= min(2, len(locality_tokens)):
        return True, "locality_token_match"

    name_tokens = text_tokens(row.get("name"))
    if name_tokens and len(name_tokens & display_tokens) >= min(2, len(name_tokens)):
        return True, "project_name_token_match"

    return False, "weak_identity_match"


def build_query(row: dict[str, str], city_id: str) -> str:
    parts = [
        clean(row.get("name")),
        clean(row.get("locality")),
        clean(row.get("pincode")),
        CITY_LABELS.get(city_id, ""),
        "India",
    ]
    return ", ".join(part for part in parts if part)


def load_project_rows(data_root: Path) -> list[dict[str, str]]:
    path = data_root / SOURCE_FILES["projects"]
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def row_needs_free_geocode(row: dict[str, str], city_id: str, scope: str) -> tuple[bool, str]:
    decision = project_coordinate_decision(row, city_id)
    if decision is None:
        return True, "unmapped"
    if scope == "low-confidence" and decision.get("source") == "validated_candidate_geocode":
        return True, "validated_candidate_geocode"
    return False, clean(decision.get("source")) or "trusted_coordinate"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES)
    parser.add_argument("--city", choices=tuple(CITY_LABELS), default=None)
    parser.add_argument("--scope", choices=("unmapped", "low-confidence"), default="low-confidence")
    parser.add_argument("--limit", type=int, default=50, help="Maximum suspicious rows to query in one run. Use 0 for no limit.")
    parser.add_argument("--sleep", type=float, default=1.1, help="Throttle between Nominatim requests.")
    parser.add_argument("--audit-only", action="store_true", help="Write suspicious rows without calling Nominatim.")
    args = parser.parse_args()

    rows = load_project_rows(args.data_root)
    candidates: list[dict[str, Any]] = []
    for row in rows:
        city_id = normalize_city(row.get("city"))
        if city_id is None or (args.city and city_id != args.city):
            continue
        needs_geocode, existing_source = row_needs_free_geocode(row, city_id, args.scope)
        if not needs_geocode:
            continue
        candidates.append({"row": row, "city_id": city_id, "query": build_query(row, city_id), "existing_source": existing_source})
        if args.limit and len(candidates) >= args.limit:
            break

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.cache.parent.mkdir(parents=True, exist_ok=True)
    args.overrides.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "project_id",
        "city_id",
        "name",
        "locality",
        "pincode",
        "existing_source",
        "query",
        "osm_lat",
        "osm_lon",
        "osm_display_name",
        "accepted",
        "acceptance_reason",
        "cache_status",
    ]
    overrides: list[dict[str, Any]] = []
    with sqlite3.connect(args.cache) as conn, args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in candidates:
            row = item["row"]
            result = {"cache_status": "audit_only"} if args.audit_only else nominatim_geocode(conn, item["query"], sleep_seconds=args.sleep)
            accepted, reason = (False, "audit_only") if args.audit_only else osm_candidate_is_accepted(row, item["city_id"], result)
            if accepted:
                overrides.append({
                    "project_id": clean(row.get("project_id")),
                    "city_id": item["city_id"],
                    "name": clean(row.get("name")),
                    "locality": clean(row.get("locality")),
                    "pincode": clean(row.get("pincode")),
                    "lat": number(result.get("lat")),
                    "lon": number(result.get("lon")),
                    "source": "free_osm_nominatim",
                    "quality": "validated_free_geocode",
                    "acceptance_reason": reason,
                    "display_name": clean(result.get("display_name")),
                    "query": item["query"],
                    "previous_coordinate_source": item["existing_source"],
                })
            writer.writerow({
                "project_id": clean(row.get("project_id")),
                "city_id": item["city_id"],
                "name": clean(row.get("name")),
                "locality": clean(row.get("locality")),
                "pincode": clean(row.get("pincode")),
                "existing_source": item["existing_source"],
                "query": item["query"],
                "osm_lat": result.get("lat"),
                "osm_lon": result.get("lon"),
                "osm_display_name": result.get("display_name"),
                "accepted": accepted,
                "acceptance_reason": reason,
                "cache_status": result.get("cache_status"),
            })
    if not args.audit_only:
        args.overrides.write_text(json.dumps({
            "schema_version": "free-osm-society-overrides-v1",
            "source": "OpenStreetMap Nominatim",
            "scope": args.scope,
            "candidate_rows": len(candidates),
            "accepted_rows": len(overrides),
            "overrides": overrides,
        }, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "candidate_rows": len(candidates),
        "accepted_rows": len(overrides),
        "output": str(args.output),
        "overrides": str(args.overrides),
        "audit_only": args.audit_only,
    }, indent=2))


if __name__ == "__main__":
    main()
