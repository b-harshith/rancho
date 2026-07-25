#!/usr/bin/env python3
"""Scrape YellowSlate school detail pages for the School Location text.

Input:
  data/output/yellowslate/yellowslate_browser_fee_schools_highest_bracket.json

Outputs:
  data/output/yellowslate/yellowslate_schools_with_locations.json
  data/output/yellowslate/yellowslate_location_scrape_report.json

The detail pages expose the location in server-rendered HTML, so this uses
plain HTTP rather than browser automation.
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data/output/yellowslate/yellowslate_browser_fee_schools_highest_bracket.json"
OUTPUT = ROOT / "data/output/yellowslate/yellowslate_schools_with_locations.json"
REPORT = ROOT / "data/output/yellowslate/yellowslate_location_scrape_report.json"


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


def clean_text(value: str) -> str:
    value = re.sub(r"<script\b[^<]*(?:(?!</script>)<[^<]*)*</script>", " ", value, flags=re.I)
    value = re.sub(r"<style\b[^<]*(?:(?!</style>)<[^<]*)*</style>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def compact_name(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def extract_pincode(address: str | None) -> str | None:
    if not address:
        return None
    normalized = re.sub(r"(?<=\d)\s+(?=\d)", "", address)
    matches = re.findall(r"\b\d{6}\b", normalized)
    return matches[-1] if matches else None


def looks_like_address(address: str, *, allow_without_pincode: bool = True) -> bool:
    if not address:
        return False
    bad_markers = (
        "Reviews Enquire",
        "Information Enquire",
        "Fee Structure",
        "About ",
        "Quick Links",
        "Yellow Slate",
    )
    if any(marker.lower() in address.lower() for marker in bad_markers):
        return False
    if extract_pincode(address):
        return True
    if not allow_without_pincode:
        return False
    address_words = (" road", " rd", " street", " cross", " main", " layout", " nagar", " bengaluru", " bangalore", " karnataka", " delhi", " noida", " gurugram", " gurgaon", " ghaziabad", " faridabad")
    return any(word in f" {address.lower()} " for word in address_words)


def extract_location(page_text: str, school_name: str | None) -> dict[str, Any]:
    """Extract location text from normalized detail-page text."""

    name = compact_name(school_name)
    candidates: list[tuple[str, str]] = []
    if name:
        candidates.extend(
            [
                (rf"{re.escape(name)}\s+Location\s+Enquire Now\s+(.*?)\s+{re.escape(name)}\s+Amenities", "name_heading_to_name_amenities"),
                (rf"{re.escape(name)}\s+Location\s+(.*?)\s+{re.escape(name)}\s+Amenities", "name_heading_to_name_amenities_no_cta"),
            ]
        )
    candidates.extend(
        [
            (r"\bSchool Location\s+Enquire Now\s+(.*?)\s+\w.{0,120}?\s+Amenities", "generic_school_location"),
            (r"\bLocation\s+Enquire Now\s+(.*?)\s+\w.{0,120}?\s+Amenities", "generic_location"),
        ]
    )

    for pattern, method in candidates:
        match = re.search(pattern, page_text, flags=re.I)
        if not match:
            continue
        address = re.sub(r"\s+", " ", match.group(1)).strip(" -|")
        # Guard against accidentally grabbing too much page chrome.
        if 12 <= len(address) <= 500 and looks_like_address(address):
            return {
                "address": address,
                "pincode": extract_pincode(address),
                "extraction_method": method,
            }

    # Fallback: locate a heading containing "Location", then stop before Amenities.
    loc = page_text.lower().find(" location ")
    if loc == -1:
        loc = page_text.lower().find("location enquire now")
    if loc != -1:
        tail = page_text[loc:]
        tail = re.sub(r"^.*?Location\s+(Enquire Now\s+)?", "", tail, flags=re.I)
        stop = re.search(r"\s+\S.{0,120}?\s+Amenities\b", tail, flags=re.I)
        address = tail[: stop.start()].strip() if stop else tail[:300].strip()
        address = re.sub(r"\s+", " ", address).strip(" -|")
        if 12 <= len(address) <= 300 and looks_like_address(address, allow_without_pincode=False):
            return {
                "address": address,
                "pincode": extract_pincode(address),
                "extraction_method": "fallback_location_to_amenities",
            }

    return {"address": None, "pincode": None, "extraction_method": None}


def fetch(url: str, retries: int, timeout: int) -> tuple[int | None, str | None, str | None]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-IN,en;q=0.9",
    }
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.status, response.read().decode("utf-8", "replace"), None
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            if exc.code < 500 or attempt == retries:
                return exc.code, body, f"HTTP {exc.code}"
            last_error = f"HTTP {exc.code}"
        except Exception as exc:  # noqa: BLE001
            last_error = repr(exc)
        time.sleep(min(8, attempt * 0.7))
    return None, None, last_error


def scrape_one(item: dict[str, Any], retries: int, timeout: int) -> dict[str, Any]:
    url = item.get("school_url")
    if not url:
        return {"school_url": None, "status": None, "error": "missing url", "location": None}
    status, body, error = fetch(url, retries, timeout)
    if body:
        text = clean_text(body)
        location = extract_location(text, item.get("school_name"))
    else:
        location = {"address": None, "pincode": None, "extraction_method": None}
    return {
        "school_url": url,
        "status": status,
        "error": error,
        "location": location,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(INPUT), help="Input JSON file path")
    parser.add_argument("--output", default=str(OUTPUT), help="Output JSON file path")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_logging(args.verbose)
    input_path = Path(args.input)
    output_path = Path(args.output)
    schools = json.loads(input_path.read_text(encoding="utf-8"))
    target_schools = schools[: args.limit] if args.limit else schools

    results_by_url: dict[str, dict[str, Any]] = {}
    logging.info("Scraping YellowSlate locations for %s schools", len(target_schools))
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(scrape_one, item, args.retries, args.timeout): item
            for item in target_schools
        }
        for i, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results_by_url[result["school_url"]] = result
            loc = result.get("location") or {}
            logging.info(
                "[%s/%s] status=%s extracted=%s url=%s",
                i,
                len(target_schools),
                result.get("status"),
                bool(loc.get("address")),
                result.get("school_url"),
            )

    for item in schools:
        result = results_by_url.get(item.get("school_url"))
        if not result:
            continue
        item["school_location"] = {
            "address": result["location"]["address"],
            "pincode": result["location"]["pincode"],
            "source_url": item.get("school_url"),
            "extraction_method": result["location"]["extraction_method"],
            "http_status": result.get("status"),
            "error": result.get("error"),
        }

    extracted = sum(1 for x in schools if (x.get("school_location") or {}).get("address"))
    failures = [
        {
            "school_name": x.get("school_name"),
            "school_url": x.get("school_url"),
            "status": (x.get("school_location") or {}).get("http_status"),
            "error": (x.get("school_location") or {}).get("error"),
        }
        for x in schools
        if x.get("school_location") and not x["school_location"].get("address")
    ]
    method_counts: dict[str, int] = {}
    pincode_count = 0
    for x in schools:
        loc = x.get("school_location") or {}
        if loc.get("address"):
            method_counts[loc.get("extraction_method") or "unknown"] = method_counts.get(loc.get("extraction_method") or "unknown", 0) + 1
        if loc.get("pincode"):
            pincode_count += 1

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_schools": len(schools),
        "attempted": len(target_schools),
        "locations_extracted": extracted,
        "location_coverage_percent": round(extracted * 100 / len(schools), 2),
        "pincodes_extracted": pincode_count,
        "method_counts": method_counts,
        "failures": failures,
    }
    output_path.write_text(json.dumps(schools, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in report if k != "failures"}, indent=2))


if __name__ == "__main__":
    main()
