#!/usr/bin/env python3
import csv
import gzip
import os
import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data/client_export/ezy_yellowslate_unified_all_cities_geocoded.csv"
GZIP_PATH = CSV_PATH.with_suffix(".csv.gz")


def below_grade_2(value):
    try:
        return bool(str(value).strip()) and float(value) < 2
    except (TypeError, ValueError):
        return False


def preschool_or_kids(row):
    name = html.unescape(str(row.get("school_name") or "")).lower()
    explicit = [
        r"\bpre[ -]?schools?\b", r"\bplay[ -]?schools?\b", r"\bkids?\b",
        r"\bkid[’']?z\b", r"\bkidz\b", r"\bkidzee\b",
        r"\bkindergarten\b", r"\bkindergarden\b", r"\bday[ -]?care\b",
        r"\bcreche\b", r"\btoddlers?\b", r"\bearly learning\b",
    ]
    if any(re.search(pattern, name) for pattern in explicit):
        return True
    # Nursery + Primary is a real grade-serving school; a standalone nursery is not.
    if re.search(r"\bnursery\b", name) and not re.search(
        r"\b(primary|elementary|secondary|high|public)\b", name
    ):
        return True
    if "montessori" in name:
        return True
    return False


def main():
    temporary = CSV_PATH.with_suffix(".filtered.tmp")
    removed = kept = preschool_removed = grade_removed = 0
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as source, open(
        temporary, "w", encoding="utf-8-sig", newline=""
    ) as target:
        reader = csv.DictReader(source)
        writer = csv.DictWriter(target, fieldnames=reader.fieldnames)
        writer.writeheader()
        for row in reader:
            if below_grade_2(row.get("highest_class")):
                grade_removed += 1
                removed += 1
                continue
            if preschool_or_kids(row):
                preschool_removed += 1
                removed += 1
                continue
            writer.writerow(row)
            kept += 1
    os.replace(temporary, CSV_PATH)
    with open(CSV_PATH, "rb") as source, gzip.open(GZIP_PATH, "wb", compresslevel=9) as target:
        while chunk := source.read(1024 * 1024):
            target.write(chunk)
    print(f"Unified schools kept: {kept:,}")
    print(f"Total schools removed: {removed:,}")
    print(f"  Grade-range removals: {grade_removed:,}")
    print(f"  Preschool/kids name removals: {preschool_removed:,}")


if __name__ == "__main__":
    main()
