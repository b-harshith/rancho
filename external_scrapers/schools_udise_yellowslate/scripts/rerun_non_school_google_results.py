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
CSV_PATH = ROOT / "data/client_export/ezy_yellowslate_unified_all_cities_geocoded.csv"
GZIP_PATH = CSV_PATH.with_suffix(".csv.gz")
CACHE = ROOT / "data/client_export/google_school_type_reruns_v2.sqlite3"
ENDPOINT = "https://maps.googleapis.com/maps/api/geocode/json"
CONCURRENCY = 12
EXTRA = [
    "school_type_rerun_status", "school_type_rerun_query",
    "school_type_original_result_types", "school_type_rerun_replaced",
]


def key(row):
    return row.get("udise_code") or "|".join([
        row.get("city", ""), row.get("normalized_name", ""),
        row.get("pincode", ""), row.get("area", ""),
    ])


def strict_query(row):
    name = (row.get("school_name") or "").strip()
    # Exact original source name plus locality is better for place discovery
    # than adding generic words or over-constraining with a street address.
    return ", ".join(filter(None, [
        name, row.get("area"), row.get("pincode"),
        (row.get("city") or "").replace("_", " "), "India",
    ]))


async def google(session, query):
    delay = 1
    for attempt in range(5):
        try:
            async with session.get(ENDPOINT, params={"address": query, "key": API_KEY}, timeout=25) as response:
                payload = await response.json(content_type=None)
            status = payload.get("status") or f"HTTP_{response.status}"
            if status == "OK":
                results = payload.get("results") or []
                school = next((item for item in results if "school" in (item.get("types") or [])), None)
                return status, school, len(results)
            if status in {"OVER_QUERY_LIMIT", "UNKNOWN_ERROR"}:
                await asyncio.sleep(delay); delay *= 2; continue
            return status, None, 0
        except Exception as exc:
            if attempt == 4:
                return f"ERROR:{type(exc).__name__}", None, 0
            await asyncio.sleep(delay); delay *= 2
    return "RETRY_EXHAUSTED", None, 0


async def main():
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source); fields = list(reader.fieldnames or []); rows = list(reader)
    for row in rows:
        row["normalized_name"] = "".join(character for character in
            (row.get("school_name") or "").lower() if character.isalnum())
    targets = [row for row in rows if "school" not in (row.get("google_result_types") or "").split("|")]
    cache = sqlite3.connect(CACHE)
    cache.execute("CREATE TABLE IF NOT EXISTS results(row_key TEXT PRIMARY KEY,payload_json TEXT NOT NULL)")
    saved = dict(cache.execute("SELECT row_key,payload_json FROM results"))
    lock = asyncio.Lock(); new_count = 0

    async def process(row, session, sem):
        nonlocal new_count
        row_key = key(row)
        if row_key in saved:
            return json.loads(saved[row_key])
        query = strict_query(row)
        async with sem:
            status, result, result_count = await google(session, query)
        payload = {"status": status, "query": query, "result": result, "result_count": result_count}
        async with lock:
            cache.execute("INSERT OR REPLACE INTO results VALUES (?,?)", (
                row_key, json.dumps(payload, ensure_ascii=False, separators=(",", ":"))))
            cache.commit(); new_count += 1
            if new_count % 100 == 0:
                print(f"Rerun Google results: {new_count:,}/{len(targets):,}", flush=True)
        return payload

    sem = asyncio.Semaphore(CONCURRENCY)
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=CONCURRENCY)) as session:
        results = await asyncio.gather(*(process(row, session, sem) for row in targets))

    target_results = {key(row): result for row, result in zip(targets, results)}
    replaced = unresolved = 0
    for row in rows:
        metadata = target_results.get(key(row))
        if not metadata:
            continue
        result = metadata.get("result") or {}
        geometry = result.get("geometry") or {}; location = geometry.get("location") or {}
        original_types = row.get("google_result_types", "")
        did_replace = bool(result and "school" in (result.get("types") or []))
        row.update({
            "school_type_rerun_status": "resolved_school_type" if did_replace else "unresolved_no_school_type",
            "school_type_rerun_query": metadata.get("query", ""),
            "school_type_original_result_types": original_types,
            "school_type_rerun_replaced": str(did_replace).lower(),
        })
        if not did_replace:
            unresolved += 1; continue
        replaced += 1
        row.update({
            "latitude": location.get("lat", row.get("latitude")),
            "longitude": location.get("lng", row.get("longitude")),
            "coordinate_source": "google_maps_api_school_typed_rerun",
            "google_formatted_address": result.get("formatted_address", ""),
            "google_place_id": result.get("place_id", ""),
            "google_location_type": geometry.get("location_type", ""),
            "google_partial_match": str(bool(result.get("partial_match"))).lower(),
            "google_result_types": "|".join(result.get("types") or []),
            "google_viewport_json": json.dumps(geometry.get("viewport"), separators=(",", ":")) if geometry.get("viewport") else "",
            "google_geocode_query": metadata.get("query", ""),
            "google_geocode_status": metadata.get("status", ""),
            "google_used_fallback_query": "false",
            "geocode_confidence": "high" if geometry.get("location_type") == "ROOFTOP" and not result.get("partial_match") else "medium",
        })

    out_fields = fields + [field for field in EXTRA if field not in fields]
    with open(CSV_PATH, "w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=out_fields); writer.writeheader(); writer.writerows(rows)
    with open(CSV_PATH, "rb") as source, gzip.open(GZIP_PATH, "wb", compresslevel=9) as target:
        while chunk := source.read(1024 * 1024): target.write(chunk)
    cache.close()
    print(f"Targeted: {len(targets):,}")
    print(f"Resolved with school type: {replaced:,}")
    print(f"Unresolved (original coordinates retained): {unresolved:,}")


if __name__ == "__main__":
    asyncio.run(main())
