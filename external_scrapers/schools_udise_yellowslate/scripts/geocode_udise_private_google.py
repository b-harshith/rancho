#!/usr/bin/env python3
import argparse
import asyncio
import csv
import json
import os
import sqlite3
from pathlib import Path

import aiohttp


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data/client_delivery/udise_private_unaided_with_enrollment.csv"
DEFAULT_OUTPUT = ROOT / "data/client_delivery/udise_private_unaided_with_google_geocoding.csv"
DEFAULT_CACHE = ROOT / "data/client_delivery/udise_private_google_geocode_cache.sqlite3"

GEOCODE_ENDPOINT = "https://maps.googleapis.com/maps/api/geocode/json"
PLACE_DETAILS_ENDPOINT = "https://maps.googleapis.com/maps/api/place/details/json"
CONCURRENCY = 12

OUTPUT_COLUMNS = [
    "udise_code",
    "school_id",
    "year_id",
    "school_name",
    "pincode",
    "state_name",
    "district_name",
    "summary_json",
    "enrollment_json",
    "latitude",
    "longitude",
    "coordinate_source",
    "google_formatted_address",
    "google_place_id",
    "google_location_type",
    "google_partial_match",
    "google_result_types",
    "google_viewport_json",
    "google_geocode_query",
    "google_geocode_status",
    "google_used_fallback_query",
    "geocode_confidence",
    "google_place_name",
    "google_place_website",
    "google_place_maps_url",
    "google_place_details_status",
]


def text(value):
    return str(value or "").strip()


def load_summary(row):
    try:
        return json.loads(row.get("summary_json") or "{}")
    except json.JSONDecodeError:
        return {}


def build_queries(row, summary):
    school_name = text(row.get("school_name") or summary.get("schoolName"))
    address = text(summary.get("address"))
    village = text(summary.get("villageName"))
    block = text(summary.get("blockName"))
    district = text(row.get("district_name") or summary.get("districtName"))
    state = text(row.get("state_name") or summary.get("stateName"))
    pincode = text(row.get("pincode") or summary.get("pincode"))

    detailed = ", ".join(filter(None, [school_name, address, village, block, district, state, pincode, "India"]))
    fallback = ", ".join(filter(None, [school_name, village, block, district, state, "India"]))
    return detailed, fallback


def confidence(result, used_fallback):
    if not result:
        return "none"
    geometry = result.get("geometry") or {}
    location_type = (geometry.get("location_type") or "").upper()
    partial = bool(result.get("partial_match"))
    if location_type == "ROOFTOP" and not partial and not used_fallback:
        return "high"
    if location_type in {"ROOFTOP", "RANGE_INTERPOLATED", "GEOMETRIC_CENTER"} and not partial:
        return "medium"
    return "low"


def init_cache(db_path):
    cache = sqlite3.connect(db_path)
    cache.execute(
        """
        CREATE TABLE IF NOT EXISTS geocodes (
            row_key TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cache.execute(
        """
        CREATE TABLE IF NOT EXISTS place_details (
            place_id TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cache.commit()
    return cache


async def request_json(session, endpoint, params):
    delay = 1
    for attempt in range(5):
        try:
            async with session.get(endpoint, params=params, timeout=30) as response:
                payload = await response.json(content_type=None)
            status = payload.get("status") or f"HTTP_{response.status}"
            if status in {"OK", "ZERO_RESULTS", "INVALID_REQUEST", "REQUEST_DENIED"}:
                return status, payload
            if status in {"OVER_QUERY_LIMIT", "UNKNOWN_ERROR"}:
                await asyncio.sleep(delay)
                delay *= 2
                continue
            return status, payload
        except Exception as exc:
            if attempt == 4:
                return f"ERROR:{type(exc).__name__}", {}
            await asyncio.sleep(delay)
            delay *= 2
    return "RETRY_EXHAUSTED", {}


async def geocode_row(session, api_key, row):
    summary = load_summary(row)
    detailed, fallback = build_queries(row, summary)
    status, payload = await request_json(session, GEOCODE_ENDPOINT, {"address": detailed, "key": api_key})
    used_fallback = False
    query = detailed
    result = (payload.get("results") or [None])[0] if status == "OK" else None
    if not result and fallback != detailed:
        status, payload = await request_json(session, GEOCODE_ENDPOINT, {"address": fallback, "key": api_key})
        used_fallback = True
        query = fallback
        result = (payload.get("results") or [None])[0] if status == "OK" else None

    geometry = (result or {}).get("geometry") or {}
    location = geometry.get("location") or {}
    return {
        "status": status,
        "query": query,
        "used_fallback": used_fallback,
        "result": result,
        "confidence": confidence(result, used_fallback),
        "latitude": location.get("lat"),
        "longitude": location.get("lng"),
    }


async def fetch_place_details(session, api_key, place_id):
    status, payload = await request_json(
        session,
        PLACE_DETAILS_ENDPOINT,
        {
            "place_id": place_id,
            "fields": "name,website,url",
            "key": api_key,
        },
    )
    result = payload.get("result") or {}
    return {
        "status": status,
        "name": result.get("name", ""),
        "website": result.get("website", ""),
        "maps_url": result.get("url", ""),
    }


async def main_async(args):
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        raise SystemExit("GOOGLE_MAPS_API_KEY is required.")

    with open(args.input, encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))

    cache = init_cache(args.cache)
    geocode_cache = dict(cache.execute("SELECT row_key,payload_json FROM geocodes"))
    details_cache = dict(cache.execute("SELECT place_id,payload_json FROM place_details"))
    lock = asyncio.Lock()
    counters = {
        "geocode_new": 0,
        "geocode_cached": 0,
        "details_new": 0,
        "details_cached": 0,
    }

    def row_key(row):
        return text(row.get("\ufeffudise_code") or row.get("udise_code"))

    async def process_row(row, session, semaphore):
        key = row_key(row)
        if key in geocode_cache:
            async with lock:
                counters["geocode_cached"] += 1
                seen = counters["geocode_cached"] + counters["geocode_new"]
                if seen % 250 == 0:
                    print(
                        f"[geocode] processed={seen:,} new={counters['geocode_new']:,} cached={counters['geocode_cached']:,}",
                        flush=True,
                    )
            return json.loads(geocode_cache[key])
        async with semaphore:
            payload = await geocode_row(session, api_key, row)
        async with lock:
            cache.execute(
                "INSERT OR REPLACE INTO geocodes(row_key,payload_json) VALUES (?,?)",
                (key, json.dumps(payload, ensure_ascii=False, separators=(",", ":"))),
            )
            cache.commit()
            counters["geocode_new"] += 1
            seen = counters["geocode_cached"] + counters["geocode_new"]
            if seen % 100 == 0:
                print(
                    f"[geocode] processed={seen:,} new={counters['geocode_new']:,} cached={counters['geocode_cached']:,} last_status={payload.get('status','')}",
                    flush=True,
                )
        return payload

    async def process_place(place_id, session, semaphore):
        if not place_id:
            return {"status": "", "name": "", "website": "", "maps_url": ""}
        if place_id in details_cache:
            async with lock:
                counters["details_cached"] += 1
                seen = counters["details_cached"] + counters["details_new"]
                if seen % 250 == 0:
                    print(
                        f"[place_details] processed={seen:,} new={counters['details_new']:,} cached={counters['details_cached']:,}",
                        flush=True,
                    )
            return json.loads(details_cache[place_id])
        async with semaphore:
            payload = await fetch_place_details(session, api_key, place_id)
        async with lock:
            cache.execute(
                "INSERT OR REPLACE INTO place_details(place_id,payload_json) VALUES (?,?)",
                (place_id, json.dumps(payload, ensure_ascii=False, separators=(",", ":"))),
            )
            cache.commit()
            counters["details_new"] += 1
            seen = counters["details_cached"] + counters["details_new"]
            if seen % 100 == 0:
                print(
                    f"[place_details] processed={seen:,} new={counters['details_new']:,} cached={counters['details_cached']:,} last_status={payload.get('status','')}",
                    flush=True,
                )
        return payload

    semaphore = asyncio.Semaphore(args.concurrency)
    connector = aiohttp.TCPConnector(limit=args.concurrency)
    async with aiohttp.ClientSession(connector=connector) as session:
        print(f"Starting geocode run for {len(rows):,} schools...", flush=True)
        geocode_results = await asyncio.gather(*(process_row(row, session, semaphore) for row in rows))
        print("Geocoding complete. Starting Google Place Details fetch...", flush=True)
        place_ids = []
        for result in geocode_results:
            geocode_result = result.get("result") or {}
            place_ids.append(text(geocode_result.get("place_id")))
        details_results = await asyncio.gather(*(process_place(place_id, session, semaphore) for place_id in place_ids))
        print("Place Details fetch complete.", flush=True)

    cache.close()

    output_rows = []
    for row, geo, details in zip(rows, geocode_results, details_results):
        source_row = {
            "udise_code": text(row.get("\ufeffudise_code") or row.get("udise_code")),
            "school_id": text(row.get("school_id")),
            "year_id": text(row.get("year_id")),
            "school_name": text(row.get("school_name")),
            "pincode": text(row.get("pincode")),
            "state_name": text(row.get("state_name")),
            "district_name": text(row.get("district_name")),
            "summary_json": row.get("summary_json") or "",
            "enrollment_json": row.get("enrollment_json") or "",
            # intentionally blank first; we only refill from fresh Google results
            "latitude": "",
            "longitude": "",
            "coordinate_source": "",
            "google_formatted_address": "",
            "google_place_id": "",
            "google_location_type": "",
            "google_partial_match": "",
            "google_result_types": "",
            "google_viewport_json": "",
            "google_geocode_query": geo.get("query", ""),
            "google_geocode_status": geo.get("status", ""),
            "google_used_fallback_query": str(bool(geo.get("used_fallback"))).lower(),
            "geocode_confidence": geo.get("confidence", "none"),
            "google_place_name": details.get("name", ""),
            "google_place_website": details.get("website", ""),
            "google_place_maps_url": details.get("maps_url", ""),
            "google_place_details_status": details.get("status", ""),
        }
        result = geo.get("result") or {}
        geometry = result.get("geometry") or {}
        location = geometry.get("location") or {}
        if location.get("lat") is not None and location.get("lng") is not None:
            source_row["latitude"] = location.get("lat")
            source_row["longitude"] = location.get("lng")
            source_row["coordinate_source"] = "google_maps_api"
            source_row["google_formatted_address"] = result.get("formatted_address", "")
            source_row["google_place_id"] = result.get("place_id", "")
            source_row["google_location_type"] = geometry.get("location_type", "")
            source_row["google_partial_match"] = str(bool(result.get("partial_match"))).lower()
            source_row["google_result_types"] = "|".join(result.get("types") or [])
            source_row["google_viewport_json"] = json.dumps(geometry.get("viewport"), separators=(",", ":")) if geometry.get("viewport") else ""
        output_rows.append(source_row)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(output_rows)

    confidence_counts = Counter(row["geocode_confidence"] for row in output_rows)
    website_count = sum(1 for row in output_rows if row["google_place_website"])
    print(f"Rows: {len(output_rows):,}")
    print(f"Confidence counts: {dict(confidence_counts)}")
    print(f"Rows with website from Place Details: {website_count:,}")
    print(f"Output: {args.output}")
    print(f"Cache: {args.cache}")


def parse_args():
    parser = argparse.ArgumentParser(description="Fresh Google geocoding for all private UDISE schools with Place Details website enrichment.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--concurrency", type=int, default=CONCURRENCY)
    return parser.parse_args()


if __name__ == "__main__":
    from collections import Counter

    asyncio.run(main_async(parse_args()))
