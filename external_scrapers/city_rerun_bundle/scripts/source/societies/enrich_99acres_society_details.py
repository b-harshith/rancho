#!/usr/bin/env python3
"""Enrich 99acres PROJECT city-page records from their detail pages.

Reads the JSONL envelopes written by scrape_99acres_societies.py, extracts and
deduplicates project records, visits each relativeUrl, and writes resumable JSONL.
"""

import argparse
import json
import os
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from curl_cffi import requests

BASE_URL = "https://www.99acres.com"
HERE = Path(__file__).resolve().parent
RAW_DIR = HERE / "data" / "raw"
COOKIE = os.environ.get("COOKIE_HEADER", "")


def log(message):
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def first(mapping, *keys):
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def project_records(path):
    projects = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            envelope = json.loads(line)
            for item in walk(envelope):
                relative = first(item, "relativeUrl", "projectUrl", "url")
                if not isinstance(relative, str) or not relative:
                    continue
                lowered = relative.lower()
                if not any(token in lowered for token in ("-r1a", "-r2a", "project", "society")):
                    continue
                url = urljoin(BASE_URL, relative)
                current = projects.setdefault(url, {})
                current.update({k: v for k, v in item.items() if not isinstance(v, (dict, list))})
                current["detail_url"] = url
                current["latitude"] = first(item, "latitude", "lat", "projectLatitude") or current.get("latitude")
                current["longitude"] = first(item, "longitude", "lng", "lon", "projectLongitude") or current.get("longitude")
    return list(projects.values())


def balanced_json_after(text, marker):
    start = text.find(marker)
    if start < 0:
        return None
    start = text.find("{", start + len(marker))
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:index + 1])
                except json.JSONDecodeError:
                    return None
    return None


def parse_units(text):
    patterns = (
        r"(?:total(?:\s+of)?|around|features|has)\s+([\d,]+)\s+(?:residential\s+)?units",
        r"([\d,]+)\s+units\s+(?:on\s+offer|in\s+total)",
    )
    for pattern in patterns:
        match = re.search(pattern, text or "", re.I)
        if match:
            value = int(match.group(1).replace(",", ""))
            if 5 <= value <= 100000:
                return value
    return None


def parse_detail(html):
    initial = balanced_json_after(html, "window.__initialData__") or {}
    state = initial.get("projectDetailState", {})
    page = state.get("pageData", {})
    components = page.get("components", {})
    summary = components.get("summaryLayer", {})
    more = components.get("moreAboutProject", {})
    layer = more.get("layerContent", {})
    rera = summary.get("rera", {})

    rera_ids = []
    for candidate in [rera.get("registrationNumber")] + [
        row.get("registrationNumber") for row in (rera.get("tuples") or [])
        if isinstance(row, dict)
    ]:
        if candidate and candidate not in rera_ids:
            rera_ids.append(candidate)

    description = more.get("description") or ""
    units = first(layer, "unitCount", "totalUnits", "numberOfUnits") or parse_units(description)
    construction = summary.get("constructionStatus") or {}
    stage = summary.get("constructionStageInfo") or {}

    result = {
        "total_units": units,
        "towers": first(layer, "towerCount", "totalTowers"),
        "floors": first(layer, "floorCount", "totalFloors"),
        "project_area": first(layer, "projectArea", "totalArea", "landArea"),
        "developer": first(summary, "builderName", "developerName") or first(layer, "builderName", "developerName"),
        "construction_status": first(construction, "label", "value") if isinstance(construction, dict) else construction,
        "possession_date": first(stage, "subLabel", "label", "value") if isinstance(stage, dict) else stage,
        "rera_ids": rera_ids,
        "resale_listings": ((components.get("resaleProperties") or {}).get("data") or {}).get("count"),
        "rental_listings": ((components.get("rentalProperties") or {}).get("data") or {}).get("count"),
        "description": description or None,
    }
    return result, bool(initial)


def load_completed(path):
    completed = set()
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                    if row.get("detail_url"):
                        completed.add(row["detail_url"])
                except (json.JSONDecodeError, TypeError):
                    pass
    return completed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", required=True)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--min-delay", type=float, default=1.0)
    parser.add_argument("--max-delay", type=float, default=2.0)
    args = parser.parse_args()

    city = args.city.strip().lower().replace(" ", "-")
    source = args.input or RAW_DIR / f"99acres_{city}_societies.jsonl"
    output = args.output or RAW_DIR / f"99acres_{city}_societies_enriched.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    projects = project_records(source)
    if args.limit:
        projects = projects[:args.limit]
    done = load_completed(output)
    log(f"Found {len(projects)} unique project detail URLs; {len(done)} already completed")

    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
    }
    if COOKIE:
        headers["cookie"] = COOKIE
    session = requests.Session()

    for index, project in enumerate(projects, 1):
        url = project["detail_url"]
        if url in done:
            continue
        row = dict(project)
        row["city_slug"] = city
        row["scraped_at"] = datetime.now(timezone.utc).isoformat()
        try:
            response = session.get(url, headers=headers, impersonate="chrome", timeout=30)
            row["http_status"] = response.status_code
            if response.status_code == 200 and "Access Denied" not in response.text:
                details, parsed = parse_detail(response.text)
                row.update(details)
                row["detail_parsed"] = parsed
            else:
                row["detail_parsed"] = False
                row["error"] = "access_denied" if "Access Denied" in response.text else f"http_{response.status_code}"
        except Exception as exc:
            row["detail_parsed"] = False
            row["error"] = str(exc)

        with output.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        log(f"[{index}/{len(projects)}] {row.get('name') or row.get('projectName') or url} | units={row.get('total_units')} | parsed={row.get('detail_parsed')}")
        time.sleep(random.uniform(args.min_delay, args.max_delay))

    log(f"Done: {output}")


if __name__ == "__main__":
    main()
