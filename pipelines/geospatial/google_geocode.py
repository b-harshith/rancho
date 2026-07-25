"""Minimal Google Geocoding client with secret-safe, expiring cache records.

The API key is accepted only through ``GOOGLE_MAPS_API_KEY``.  It is never
included in a cache key, saved request URL, exception, or output artifact.
Google results are reference points/viewports, not boundary polygons.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ENDPOINT = "https://maps.googleapis.com/maps/api/geocode/json"
DEFAULT_TTL_DAYS = 29  # below Google's documented 30-day lat/lng cache limit


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _cache_key(query: str) -> str:
    return hashlib.sha256(query.strip().casefold().encode("utf-8")).hexdigest()


def _redacted_request(query: str) -> str:
    return f"{ENDPOINT}?address={urllib.parse.quote_plus(query)}&key=REDACTED"


def _summarize(query: str, payload: dict, *, fetched_at: datetime, ttl_days: int) -> dict:
    results = []
    for item in payload.get("results", []):
        geometry = item.get("geometry", {})
        results.append(
            {
                "formatted_address": item.get("formatted_address"),
                "place_id": item.get("place_id"),
                "types": item.get("types", []),
                "location": geometry.get("location"),
                "location_type": geometry.get("location_type"),
                "viewport": geometry.get("viewport"),
                "bounds": geometry.get("bounds"),
                "address_components": item.get("address_components", []),
            }
        )
    return {
        "schema_version": "1.0",
        "provider": "google_geocoding_api",
        "query": query,
        "request_url_redacted": _redacted_request(query),
        "status": payload.get("status"),
        "fetched_at": fetched_at.isoformat(),
        "expires_at": (fetched_at + timedelta(days=ttl_days)).isoformat(),
        "results": results,
    }


def geocode(query: str, cache_dir: Path, *, ttl_days: int = DEFAULT_TTL_DAYS) -> dict:
    key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not key:
        raise RuntimeError("GOOGLE_MAPS_API_KEY is required in the runtime environment")
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{_cache_key(query)}.json"
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        expires_at = datetime.fromisoformat(cached["expires_at"])
        if _utc_now() < expires_at:
            return cached

    parameters = urllib.parse.urlencode({"address": query, "key": key})
    request = urllib.request.Request(
        f"{ENDPOINT}?{parameters}",
        headers={"User-Agent": "BangaloreRancho-geospatial-preflight/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        # Do not include exc.url: it contains the credential.
        raise RuntimeError(f"Google Geocoding HTTP status {exc.code}") from None
    record = _summarize(query, payload, fetched_at=_utc_now(), ttl_days=ttl_days)
    cache_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    time.sleep(0.05)
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("queries", nargs="+")
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--ttl-days", type=int, default=DEFAULT_TTL_DAYS)
    args = parser.parse_args()
    if not 1 <= args.ttl_days <= 29:
        parser.error("--ttl-days must be between 1 and 29")
    for query in args.queries:
        record = geocode(query, args.cache_dir, ttl_days=args.ttl_days)
        print(json.dumps({"query": query, "status": record["status"], "results": len(record["results"])}))


if __name__ == "__main__":
    main()
