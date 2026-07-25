#!/usr/bin/env python3
import asyncio
import csv
import gzip
import json
import sqlite3
from pathlib import Path

import aiohttp
from scripts.predict_enrollment_and_compile import API_KEY

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data/client_export/ezy_yellowslate_unified_all_cities.csv"
OUTPUT = ROOT / "data/client_export/ezy_yellowslate_unified_all_cities_geocoded.csv"
COMPRESSED = ROOT / "data/client_export/ezy_yellowslate_unified_all_cities_geocoded.csv.gz"
CACHE = ROOT / "data/client_export/google_geocode_metadata.sqlite3"
ENDPOINT = "https://maps.googleapis.com/maps/api/geocode/json"
CONCURRENCY = 12

EXTRA_COLUMNS = [
    "google_formatted_address", "google_place_id", "google_location_type",
    "google_partial_match", "google_result_types", "google_viewport_json",
    "google_geocode_query", "google_geocode_status", "google_used_fallback_query",
    "geocode_confidence",
]


def confidence(result, used_fallback):
    if not result:
        return "none"
    location_type = ((result.get("geometry") or {}).get("location_type") or "").upper()
    partial = bool(result.get("partial_match"))
    if location_type == "ROOFTOP" and not partial and not used_fallback:
        return "high"
    if location_type in {"ROOFTOP", "RANGE_INTERPOLATED", "GEOMETRIC_CENTER"} and not partial:
        return "medium"
    return "low"


def queries(row):
    detailed = ", ".join(filter(None, [
        row.get("school_name"), row.get("address"), row.get("area"),
        row.get("pincode"), row.get("city", "").replace("_", " "), "India",
    ]))
    fallback = ", ".join(filter(None, [
        row.get("school_name"), row.get("area"),
        row.get("city", "").replace("_", " "), "India",
    ]))
    return detailed, fallback


async def request_google(session, query):
    delay = 1
    for attempt in range(5):
        try:
            async with session.get(ENDPOINT, params={"address": query, "key": API_KEY}, timeout=25) as response:
                payload = await response.json(content_type=None)
            status = payload.get("status") or f"HTTP_{response.status}"
            if status == "OK":
                return status, payload.get("results", [])[0]
            if status in {"OVER_QUERY_LIMIT", "UNKNOWN_ERROR"}:
                await asyncio.sleep(delay)
                delay *= 2
                continue
            return status, None
        except Exception as exc:
            if attempt == 4:
                return f"ERROR:{type(exc).__name__}", None
            await asyncio.sleep(delay)
            delay *= 2
    return "RETRY_EXHAUSTED", None


async def main():
    with open(INPUT, encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    cache = sqlite3.connect(CACHE)
    cache.execute("""CREATE TABLE IF NOT EXISTS geocodes (
        row_key TEXT PRIMARY KEY, payload_json TEXT NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    cached = dict(cache.execute("SELECT row_key,payload_json FROM geocodes"))
    lock = asyncio.Lock()
    completed = 0

    def row_key(row):
        return row.get("udise_code") or "|".join([
            row.get("city", ""), row.get("normalized_name", ""),
            row.get("pincode", ""), row.get("area", ""),
        ])

    async def process(row, session, semaphore):
        nonlocal completed
        key = row_key(row)
        if key in cached:
            return json.loads(cached[key])
        detailed, fallback = queries(row)
        async with semaphore:
            status, result = await request_google(session, detailed)
            used_fallback = False
            query = detailed
            if not result and fallback != detailed:
                status, result = await request_google(session, fallback)
                used_fallback = True
                query = fallback
        geometry = (result or {}).get("geometry") or {}
        location = geometry.get("location") or {}
        payload = {
            "status": status,
            "query": query,
            "used_fallback": used_fallback,
            "result": result,
            "confidence": confidence(result, used_fallback),
            "latitude": location.get("lat"),
            "longitude": location.get("lng"),
        }
        async with lock:
            cache.execute(
                "INSERT OR REPLACE INTO geocodes(row_key,payload_json) VALUES (?,?)",
                (key, json.dumps(payload, ensure_ascii=False, separators=(",", ":"))),
            )
            cache.commit()
            completed += 1
            if completed % 100 == 0:
                print(f"New Google results: {completed:,}; cached before run: {len(cached):,}", flush=True)
        return payload

    semaphore = asyncio.Semaphore(CONCURRENCY)
    connector = aiohttp.TCPConnector(limit=CONCURRENCY)
    async with aiohttp.ClientSession(connector=connector) as session:
        results = await asyncio.gather(*(process(row, session, semaphore) for row in rows))

    for row, metadata in zip(rows, results):
        result = metadata.get("result") or {}
        geometry = result.get("geometry") or {}
        location = geometry.get("location") or {}
        if location.get("lat") is not None and location.get("lng") is not None:
            row["latitude"] = location["lat"]
            row["longitude"] = location["lng"]
            row["coordinate_source"] = "google_maps_api"
        row.update({
            "google_formatted_address": result.get("formatted_address", ""),
            "google_place_id": result.get("place_id", ""),
            "google_location_type": geometry.get("location_type", ""),
            "google_partial_match": str(bool(result.get("partial_match"))).lower() if result else "",
            "google_result_types": "|".join(result.get("types") or []),
            "google_viewport_json": json.dumps(geometry.get("viewport"), separators=(",", ":")) if geometry.get("viewport") else "",
            "google_geocode_query": metadata.get("query", ""),
            "google_geocode_status": metadata.get("status", ""),
            "google_used_fallback_query": str(bool(metadata.get("used_fallback"))).lower(),
            "geocode_confidence": metadata.get("confidence", "none"),
        })

    output_fields = fieldnames + [column for column in EXTRA_COLUMNS if column not in fieldnames]
    with open(OUTPUT, "w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=output_fields)
        writer.writeheader()
        writer.writerows(rows)
    with open(OUTPUT, "rb") as source, gzip.open(COMPRESSED, "wb", compresslevel=9) as target:
        while chunk := source.read(1024 * 1024):
            target.write(chunk)
    cache.close()

    counts = {}
    for result in results:
        level = result.get("confidence", "none")
        counts[level] = counts.get(level, 0) + 1
    print(f"Rows: {len(rows):,}")
    print(f"Confidence: {counts}")
    print(f"CSV: {OUTPUT} ({OUTPUT.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"Gzip: {COMPRESSED} ({COMPRESSED.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    asyncio.run(main())
