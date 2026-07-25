#!/usr/bin/env python3
"""
Extract MagicBricks Bangalore commercial listings from the latest processed
dataset and store them in a dedicated folder.

Inputs:
    data/processed/processed_bangalore.json

Outputs:
    data/processed/bangalore_commercial/magicbricks_commercial.json
    data/processed/bangalore_commercial/magicbricks_commercial.csv
"""

from __future__ import annotations

import csv
import json
import argparse
from collections import Counter
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_JSON = BASE_DIR / "data" / "processed" / "processed_bangalore.json"
OUTPUT_DIR = BASE_DIR / "data" / "processed" / "bangalore_commercial"
OUTPUT_JSON = OUTPUT_DIR / "magicbricks_commercial.json"
OUTPUT_CSV = OUTPUT_DIR / "magicbricks_commercial.csv"


COMMERCIAL_TYPES = {
    "Commercial Office Space",
    "Commercial Land",
    "Commercial Shop",
    "Commercial Showroom",
    "Commercial Building",
    "Industrial Land",
    "Industrial Building",
    "Industrial Shed",
    "Office in IT Park/ SEZ",
    "Office in IT Park/SEZ",
    "Retail Shop",
    "Showroom",
    "Warehouse / Godown",
    "Cold Storage",
}

LAND_TYPES = {
    "Commercial Land",
    "Industrial Land",
}


def is_commercial(record: dict) -> bool:
    """Return True when a listing should be treated as commercial."""
    property_type = record.get("property_type")
    if property_type in LAND_TYPES:
        return False
    if record.get("listing_category") == "Commercial":
        return True
    return property_type in COMMERCIAL_TYPES


def csv_value(value):
    """Convert values to CSV-safe strings."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def parse_confidence_score(value) -> float:
    """Coerce confidence score values to a numeric form."""
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def main(min_confidence: float = 50.0) -> None:
    if not INPUT_JSON.exists():
        raise FileNotFoundError(f"Missing input file: {INPUT_JSON}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with INPUT_JSON.open("r", encoding="utf-8") as f:
        all_records = json.load(f)

    commercial_records = []
    property_counts = Counter()
    transaction_counts = Counter()
    removed_low_confidence = 0
    removed_land = 0

    for record in all_records:
        if not isinstance(record, dict) or not is_commercial(record):
            if isinstance(record, dict) and record.get("property_type") in LAND_TYPES:
                removed_land += 1
            continue

        score = parse_confidence_score(record.get("confidence_score"))
        if score < min_confidence:
            removed_low_confidence += 1
            continue

        cleaned = dict(record)
        cleaned.setdefault("source_portal", "Magicbricks")
        commercial_records.append(cleaned)

        property_counts[cleaned.get("property_type") or "Unknown"] += 1
        transaction_counts[cleaned.get("transaction_type") or "Unknown"] += 1

    if not commercial_records:
        raise RuntimeError("No commercial MagicBricks listings were found.")

    # Preserve field order as encountered, while forcing source_portal to the front.
    fieldnames = ["source_portal"]
    seen_fields = {"source_portal"}
    for record in commercial_records:
        for key in record.keys():
            if key not in seen_fields:
                fieldnames.append(key)
                seen_fields.add(key)

    with OUTPUT_JSON.open("w", encoding="utf-8") as f:
        json.dump(commercial_records, f, ensure_ascii=False, indent=2)

    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for record in commercial_records:
            writer.writerow({key: csv_value(record.get(key)) for key in fieldnames})

    summary = {
        "input_file": str(INPUT_JSON.relative_to(BASE_DIR)),
        "output_json": str(OUTPUT_JSON.relative_to(BASE_DIR)),
        "output_csv": str(OUTPUT_CSV.relative_to(BASE_DIR)),
        "min_confidence": min_confidence,
        "commercial_count": len(commercial_records),
        "removed_low_confidence": removed_low_confidence,
        "removed_land": removed_land,
        "property_types": dict(property_counts.most_common()),
        "transaction_types": dict(transaction_counts.most_common()),
    }

    summary_path = OUTPUT_DIR / "summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"Saved {len(commercial_records):,} commercial listings to {OUTPUT_DIR}")
    print(f"  Min confidence: {min_confidence:g}")
    print(f"  Removed low-confidence rows: {removed_low_confidence:,}")
    print(f"  Removed land rows: {removed_land:,}")
    print(f"  JSON : {OUTPUT_JSON}")
    print(f"  CSV  : {OUTPUT_CSV}")
    print(f"  Meta : {summary_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract Bangalore commercial MagicBricks listings")
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=50.0,
        help="Minimum confidence score to keep a listing (default: 50)",
    )
    args = parser.parse_args()
    main(min_confidence=args.min_confidence)
