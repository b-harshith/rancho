#!/usr/bin/env python3
"""Scrape YellowSlate school fee-bracket search results.

The script is deliberately HTTP/RSC based, not DOM based. YellowSlate is a
Next.js site and its result pages often embed school records directly in the
React Server Component payload as JSON objects containing fields such as
``slate_id``, ``slate_name``, ``slate_slug`` and ``feeRange``.

Outputs:
  data/output/yellowslate/yellowslate_fee_schools.json
  data/output/yellowslate/yellowslate_fee_schools_raw_records.json
  data/output/yellowslate/yellowslate_fee_scrape_report.json

Example:
  python3 scripts/scrape_yellowslate_fees.py --workers 8

If the direct /search route returns a city/session error, use:
  python3 scripts/scrape_yellowslate_fees.py --route city --workers 8

The city route is useful for diagnostics but may not always honor the fee
filter the same way as the browser's /search route, so the report includes
fee-bracket leakage checks.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data/output/yellowslate"
RAW_DIR = OUT_DIR / "raw_pages"

BASE_URL = "https://yellowslate.com"
DEFAULT_RSC = "i31tq"
DEFAULT_CITY = {
    "cityId": 13,
    "cityName": "Bengaluru",
    "lat": "12.9715987",
    "lan": "77.5945627",
    "citySlug": "bengaluru",
    "is_popular": 1,
    "is_sitemap": 0,
    "country_id": 1,
}


@dataclass(frozen=True)
class FeeBracket:
    key: str
    label: str
    fee_param: str
    min_fee: int
    max_fee: int | None
    total_pages: int


FEE_BRACKETS = [
    FeeBracket("under_30k", "Under 30 K", "0-30000", 0, 30000, 72),
    FeeBracket("30k_50k", "Above 30 K And Under 50 K", "30000-50000", 30000, 50000, 73),
    FeeBracket("50k_70k", "Above 50 K And Under 70 K", "50000-70000", 50000, 70000, 30),
    FeeBracket("70k_1l", "Above 70 K And Under 1 Lac", "70000-100000", 70000, 100000, 18),
    FeeBracket("1l_2l", "Above 1 Lac And Under 2 Lac", "100000-200000", 100000, 200000, 23),
    FeeBracket("above_2l", "Above 2 Lac", "200000-99999999", 200000, None, 3),
]


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


def city_cookie(city: dict[str, Any]) -> str:
    encoded = urllib.parse.quote(json.dumps(city, separators=(",", ":")))
    # YellowSlate components read both names in different places.
    return f"current_city={encoded}; city={encoded}"


def build_url(
    bracket: FeeBracket,
    page: int,
    *,
    route: str,
    city_slug: str,
    rsc: str,
) -> str:
    params = {"fee": bracket.fee_param, "_rsc": rsc}
    if page > 1:
        params["page"] = str(page)
    query = urllib.parse.urlencode(params)
    if route == "search":
        return f"{BASE_URL}/search?{query}"
    if route == "city":
        return f"{BASE_URL}/schools/{city_slug}?{query}"
    raise ValueError(f"Unknown route: {route}")


def request_headers(city: dict[str, Any], *, route: str) -> dict[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "RSC": "1",
    }
    if route == "search":
        headers["Cookie"] = city_cookie(city)
        headers["Referer"] = f"{BASE_URL}/schools/{city.get('citySlug', 'bengaluru')}"
    return headers


def fetch_text(url: str, headers: dict[str, str], *, retries: int, timeout: int) -> tuple[int, str]:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                body = response.read().decode("utf-8", "replace")
                return response.status, body
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            # Keep 4xx/5xx bodies for diagnostics; retry 5xx.
            if exc.code < 500 or attempt == retries:
                return exc.code, body
            last_error = exc
        except Exception as exc:  # noqa: BLE001 - logged with URL context
            last_error = exc
        sleep = min(8.0, 0.7 * attempt) + random.random() * 0.4
        logging.debug("Retrying %s after error on attempt %s: %r", url, attempt, last_error)
        time.sleep(sleep)
    raise RuntimeError(f"Failed to fetch {url}: {last_error!r}")


def extract_school_records(payload: str) -> list[dict[str, Any]]:
    """Extract embedded YellowSlate school objects from HTML/RSC payload."""

    decoder = json.JSONDecoder()
    records: list[dict[str, Any]] = []
    seen_offsets: set[int] = set()

    # Normal RSC payloads contain raw JSON fragments like {"slate_id":...}.
    for marker in ('{"slate_id"', '{\\"slate_id\\"'):
        start = 0
        while True:
            pos = payload.find(marker, start)
            if pos == -1:
                break
            start = pos + 1
            if pos in seen_offsets:
                continue
            seen_offsets.add(pos)
            candidate = payload[pos:]
            if marker.startswith("{\\"):
                # Convert a quoted/escaped JSON fragment back to normal text.
                candidate = candidate.replace('\\"', '"').replace("\\/", "/")
            try:
                obj, end = decoder.raw_decode(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and obj.get("slate_id") and obj.get("slate_name"):
                records.append(obj)

    # Deduplicate records that can appear in both raw and escaped forms.
    unique: dict[str, dict[str, Any]] = {}
    for record in records:
        key = str(record.get("slate_id") or record.get("slate_slug") or record.get("slate_name"))
        unique[key] = record
    return list(unique.values())


def safe_int(value: Any) -> int | None:
    if value in (None, "", "null", "undefined"):
        return None
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


def school_url(slug: str | None) -> str | None:
    if not slug:
        return None
    slug = str(slug).strip("/")
    if slug.startswith("uae/"):
        return f"{BASE_URL}/school/{slug}"
    return f"{BASE_URL}/school/{slug}"


def normalize_record(record: dict[str, Any], bracket: FeeBracket, page: int, source_url: str) -> dict[str, Any]:
    info = record.get("schoolInfo") or {}
    fee = record.get("feeRange") or {}
    city = record.get("cityInfo") or {}
    area = record.get("areaInfo") or {}
    slug = record.get("slate_slug")
    min_fee = safe_int(fee.get("min_fee"))
    max_fee = safe_int(fee.get("max_fee"))

    return {
        "source": "yellowslate",
        "slate_id": record.get("slate_id"),
        "school_name": record.get("slate_name"),
        "school_url": school_url(slug),
        "slate_slug": slug,
        "fee": {
            "min_fee": min_fee,
            "max_fee": max_fee,
            "fee_range_raw": fee.get("fee_range"),
            "search_bracket_key": bracket.key,
            "search_bracket_label": bracket.label,
            "search_bracket_min": bracket.min_fee,
            "search_bracket_max": bracket.max_fee,
        },
        "location": {
            "city": city.get("cityName"),
            "city_slug": city.get("citySlug"),
            "area": area.get("areaName"),
            "area_slug": area.get("areaSlug"),
            "address": info.get("address"),
            "latitude": safe_float(record.get("lat")),
            "longitude": safe_float(record.get("lng")),
        },
        "contact": {
            "phone": info.get("phone") or record.get("phone"),
            "email": info.get("email"),
            "website": info.get("website"),
        },
        "academics": {
            "board": info.get("board"),
            "board1": info.get("board1"),
            "board2": info.get("board2"),
            "medium": info.get("medium"),
            "grade_from": info.get("grade_from"),
            "grade_to": info.get("grade_to"),
            "school_type_text": info.get("school_type_text"),
            "collection_type": info.get("collection_type"),
            "collection_type1": info.get("collection_type1"),
        },
        "yellowslate_meta": {
            "claimed": record.get("claimed"),
            "is_client": record.get("is_client"),
            "views": record.get("views"),
            "admissions_open": record.get("admissions_open"),
            "near_client": record.get("near_client"),
            "source_page": page,
            "source_url": source_url,
        },
    }


def safe_float(value: Any) -> float | None:
    if value in (None, "", "null", "undefined"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fee_fits_bracket(item: dict[str, Any]) -> bool | None:
    min_fee = item["fee"]["min_fee"]
    max_fee = item["fee"]["max_fee"]
    lo = item["fee"]["search_bracket_min"]
    hi = item["fee"]["search_bracket_max"]
    value = min_fee if min_fee is not None else max_fee
    if value is None:
        return None
    if hi is None:
        return value >= lo
    return lo <= value <= hi


def scrape_page(
    bracket: FeeBracket,
    page: int,
    args: argparse.Namespace,
    headers: dict[str, str],
) -> dict[str, Any]:
    url = build_url(bracket, page, route=args.route, city_slug=args.city_slug, rsc=args.rsc)
    status, payload = fetch_text(url, headers, retries=args.retries, timeout=args.timeout)
    records = extract_school_records(payload)

    if args.save_raw:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        raw_path = RAW_DIR / f"{bracket.key}_page_{page:03d}_status_{status}.txt"
        raw_path.write_text(payload)

    error_markers = []
    for marker in ("Your search results need City", '"digest"', "Internal Server Error"):
        if marker in payload:
            error_markers.append(marker)

    return {
        "bracket": bracket,
        "page": page,
        "url": url,
        "status": status,
        "records": records,
        "payload_size": len(payload),
        "error_markers": error_markers,
    }


def merge_records(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedupe by Slate id/URL while preserving all observed fee brackets."""

    merged: dict[str, dict[str, Any]] = {}
    for item in items:
        key = str(item.get("slate_id") or item.get("school_url") or item.get("school_name"))
        if key not in merged:
            item["observed_fee_brackets"] = []
            merged[key] = item
        target = merged[key]
        bracket_observation = {
            "bracket_key": item["fee"]["search_bracket_key"],
            "bracket_label": item["fee"]["search_bracket_label"],
            "source_page": item["yellowslate_meta"]["source_page"],
            "source_url": item["yellowslate_meta"]["source_url"],
            "fee_fits_bracket": fee_fits_bracket(item),
        }
        target["observed_fee_brackets"].append(bracket_observation)

        # If the same school appears multiple times, keep the richest fee range.
        current_span = (target["fee"]["max_fee"] or 0) - (target["fee"]["min_fee"] or 0)
        new_span = (item["fee"]["max_fee"] or 0) - (item["fee"]["min_fee"] or 0)
        if new_span > current_span:
            target["fee"].update(item["fee"])
    return sorted(merged.values(), key=lambda x: (str(x.get("school_name") or ""), str(x.get("slate_id") or "")))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route", choices=["search", "city"], default="search")
    parser.add_argument("--city-slug", default="bengaluru")
    parser.add_argument("--rsc", default=DEFAULT_RSC)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--save-raw", action="store_true", help="Save every fetched payload under data/output/yellowslate/raw_pages")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--max-pages-per-bracket", type=int, default=None, help="Debug limiter")
    parser.add_argument("--only-bracket", choices=[b.key for b in FEE_BRACKETS], default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    configure_logging(args.verbose)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    city = dict(DEFAULT_CITY)
    city["citySlug"] = args.city_slug
    if args.city_slug == "bengaluru":
        city.update(DEFAULT_CITY)

    headers = request_headers(city, route=args.route)
    selected = [b for b in FEE_BRACKETS if args.only_bracket in (None, b.key)]
    tasks: list[tuple[FeeBracket, int]] = []
    for bracket in selected:
        pages = bracket.total_pages
        if args.max_pages_per_bracket:
            pages = min(pages, args.max_pages_per_bracket)
        for page in range(1, pages + 1):
            tasks.append((bracket, page))

    logging.info("Scraping %s YellowSlate pages using route=%s workers=%s", len(tasks), args.route, args.workers)

    all_raw_records: list[dict[str, Any]] = []
    normalized: list[dict[str, Any]] = []
    page_reports: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(scrape_page, bracket, page, args, headers) for bracket, page in tasks]
        for idx, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            bracket: FeeBracket = result["bracket"]
            records = result["records"]
            logging.info(
                "[%s/%s] %s page %s status=%s records=%s markers=%s",
                idx,
                len(tasks),
                bracket.key,
                result["page"],
                result["status"],
                len(records),
                ",".join(result["error_markers"]) or "-",
            )
            page_reports.append(
                {
                    "bracket_key": bracket.key,
                    "bracket_label": bracket.label,
                    "page": result["page"],
                    "url": result["url"],
                    "status": result["status"],
                    "records": len(records),
                    "payload_size": result["payload_size"],
                    "error_markers": result["error_markers"],
                }
            )
            for record in records:
                all_raw_records.append(
                    {
                        "bracket_key": bracket.key,
                        "bracket_label": bracket.label,
                        "page": result["page"],
                        "source_url": result["url"],
                        "record": record,
                    }
                )
                normalized.append(normalize_record(record, bracket, result["page"], result["url"]))

    schools = merge_records(normalized)
    fee_fit_counts: dict[str, int] = {}
    for item in normalized:
        fee_fit_counts[str(fee_fits_bracket(item))] = fee_fit_counts.get(str(fee_fits_bracket(item)), 0) + 1

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "route": args.route,
        "city_slug": args.city_slug,
        "rsc": args.rsc,
        "expected_total_from_user": 2871,
        "pages_requested": len(tasks),
        "raw_records": len(all_raw_records),
        "unique_schools": len(schools),
        "records_by_bracket": {
            bracket.key: sum(1 for item in normalized if item["fee"]["search_bracket_key"] == bracket.key)
            for bracket in FEE_BRACKETS
        },
        "unique_by_observed_bracket": {
            bracket.key: len(
                {
                    str(item.get("slate_id") or item.get("school_url"))
                    for item in normalized
                    if item["fee"]["search_bracket_key"] == bracket.key
                }
            )
            for bracket in FEE_BRACKETS
        },
        "fee_fits_requested_bracket_counts": fee_fit_counts,
        "pages_with_zero_records": [p for p in page_reports if p["records"] == 0],
        "pages_with_errors": [p for p in page_reports if p["status"] >= 400 or p["error_markers"]],
        "page_reports": sorted(page_reports, key=lambda x: (x["bracket_key"], x["page"])),
    }

    (OUT_DIR / "yellowslate_fee_schools.json").write_text(json.dumps(schools, ensure_ascii=False, indent=2) + "\n")
    (OUT_DIR / "yellowslate_fee_schools_raw_records.json").write_text(
        json.dumps(all_raw_records, ensure_ascii=False, indent=2) + "\n"
    )
    (OUT_DIR / "yellowslate_fee_scrape_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    logging.info("Wrote %s unique schools", len(schools))
    print(json.dumps({k: report[k] for k in ("pages_requested", "raw_records", "unique_schools", "pages_with_zero_records", "pages_with_errors")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
