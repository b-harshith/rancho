#!/usr/bin/env python3
"""Flatten page-oriented JSONL captures into a single JSON array.

The 99acres scrapers in this bundle emit one JSON object per response page.
This helper extracts the actual locality / society records from each page body
and writes a deduplicated list that downstream scripts can consume directly.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable


COLLECTION_KEYS = ("tuples", "localities", "projects", "results", "items")
RECORD_HINT_KEYS = (
    "id",
    "slug",
    "name",
    "localityName",
    "locality_name",
    "seoContent",
    "rei",
    "propCount",
)


def load_jsonl(path: Path) -> list[Any]:
    records: list[Any] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def iter_record_candidates(payload: Any) -> Iterable[dict[str, Any]]:
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                yield item
        return

    if not isinstance(payload, dict):
        return

    nested = payload.get("data")
    if isinstance(nested, list):
        for item in nested:
            if isinstance(item, dict):
                yield item
        return
    if isinstance(nested, dict):
        yielded = False
        for key in COLLECTION_KEYS:
            items = nested.get(key)
            if isinstance(items, list):
                yielded = True
                for item in items:
                    if isinstance(item, dict):
                        yield item
        if yielded:
            return

    yielded = False
    for key in COLLECTION_KEYS:
        items = payload.get(key)
        if isinstance(items, list):
            yielded = True
            for item in items:
                if isinstance(item, dict):
                    yield item
    if yielded:
        return

    if any(key in payload for key in RECORD_HINT_KEYS):
        yield payload


def dedupe_key(record: dict[str, Any]) -> str:
    seo = record.get("seoContent")
    seo_url = seo.get("url") if isinstance(seo, dict) else None
    values = [
        record.get("id"),
        record.get("slug"),
        record.get("localityId"),
        record.get("locality_id"),
        seo_url,
        record.get("url"),
        record.get("name"),
        record.get("localityName"),
    ]
    for value in values:
        if value is not None and str(value).strip():
            return str(value).strip()
    return json.dumps(record, sort_keys=True, ensure_ascii=False)


def flatten_jsonl(input_path: Path) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()

    for page in load_jsonl(input_path):
        for record in iter_record_candidates(page):
            key = dedupe_key(record)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(record)

    return deduped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Path to the source JSONL file")
    parser.add_argument("--output", required=True, help="Path to the flattened JSON file")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    records = flatten_jsonl(input_path)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(records, handle, indent=2, ensure_ascii=False)

    print(f"Flattened {len(records)} records from {input_path} -> {output_path}")


if __name__ == "__main__":
    main()
