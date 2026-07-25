#!/usr/bin/env python3
import gzip
import json
import shutil
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/runtime/udise_data.sqlite3"
OUT_DIR = ROOT / "data/client_export"
OUTPUT = OUT_DIR / "udise_schools_client.sqlite3"
COMPRESSED = OUT_DIR / "udise_schools_client.sqlite3.gz"
README = OUT_DIR / "WHATSAPP_MESSAGE.txt"

COORDINATE_KEYS = {
    "latitude", "longitude", "lat", "lon", "lng", "schoolLatitude",
    "schoolLongitude", "schLatitude", "schLongitude",
}


def strip_coordinates(value):
    if isinstance(value, dict):
        return {
            key: strip_coordinates(child)
            for key, child in value.items()
            if key not in COORDINATE_KEYS and key.lower() not in {"latitude", "longitude"}
        }
    if isinstance(value, list):
        return [strip_coordinates(child) for child in value]
    return value


def clean_json(raw):
    try:
        return json.dumps(strip_coordinates(json.loads(raw or "{}")), separators=(",", ":"), ensure_ascii=False)
    except (TypeError, json.JSONDecodeError):
        return "{}"


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.unlink(missing_ok=True)
    COMPRESSED.unlink(missing_ok=True)

    source = sqlite3.connect(f"file:{SOURCE}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    target = sqlite3.connect(OUTPUT)
    target.executescript("""
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        PRAGMA temp_store=MEMORY;
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE schools (
            udise_code TEXT PRIMARY KEY,
            school_id TEXT,
            year_id TEXT,
            school_name TEXT,
            pincode TEXT,
            state_name TEXT,
            district_name TEXT,
            summary_json TEXT NOT NULL,
            enrollment_json TEXT
        );
        CREATE INDEX idx_client_school_name ON schools(school_name);
        CREATE INDEX idx_client_pincode ON schools(pincode);
        CREATE INDEX idx_client_school_context ON schools(school_id, year_id);
    """)

    # Highest row id is the latest collected copy of each UDISE code.
    rows = source.execute("""
        SELECT s.* FROM schools s
        JOIN (SELECT udise_code, MAX(id) id FROM schools
              WHERE udise_code IS NOT NULL AND TRIM(udise_code) != ''
              GROUP BY udise_code) latest ON latest.id=s.id
        ORDER BY s.udise_code
    """)
    insert_school = """INSERT INTO schools
        (udise_code,school_id,year_id,school_name,pincode,state_name,district_name,summary_json)
        VALUES (?,?,?,?,?,?,?,?)"""
    count = 0
    for row in rows:
        summary_text = clean_json(row["summary_json"])
        summary = json.loads(summary_text)
        target.execute(insert_school, (
            row["udise_code"], row["school_id"], row["year_id"], row["school_name"],
            row["pincode"], summary.get("stateName"), summary.get("districtName"), summary_text,
        ))
        count += 1
        if count % 5000 == 0:
            target.commit()
            print(f"Exported {count:,} schools...", flush=True)
    target.commit()

    # Stream only enrollment responses. Newer response ids replace older copies.
    enrollment_rows = source.execute("""
        SELECT id,school_id,year_id,COALESCE(body_json,body_text) body
        FROM network_responses
        WHERE url LIKE '%/school-statistics/enrolment-teacher?%'
          AND COALESCE(body_json,body_text) IS NOT NULL
        ORDER BY id
    """)
    enrollment_count = 0
    for row in enrollment_rows:
        target.execute(
            # school_id is stable; report-card collection normalizes some source
            # year ids (for example 13 -> 11), so year_id is not a safe join key.
            "UPDATE schools SET enrollment_json=? WHERE school_id=?",
            (row["body"], row["school_id"]),
        )
        enrollment_count += 1
        if enrollment_count % 5000 == 0:
            target.commit()
            print(f"Processed {enrollment_count:,} enrollment responses...", flush=True)
    target.commit()

    stats = target.execute("""
        SELECT COUNT(*) schools,
               COUNT(DISTINCT district_name) cities,
               COUNT(DISTINCT pincode) pincodes,
               SUM(enrollment_json IS NOT NULL) with_enrollment
        FROM schools
    """).fetchone()
    metadata = {
        "total_schools": str(stats[0]),
        "total_cities": str(stats[1]),
        "city_definition": "Distinct UDISE district_name values",
        "total_pincodes": str(stats[2]),
        "schools_with_enrollment": str(stats[3]),
        "coordinates_removed": "true",
    }
    target.executemany("INSERT INTO metadata(key,value) VALUES (?,?)", metadata.items())
    target.commit()
    target.execute("VACUUM")
    target.close()
    source.close()

    with open(OUTPUT, "rb") as src, gzip.open(COMPRESSED, "wb", compresslevel=9) as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)

    message = (
        "UDISE School Database\n\n"
        f"Total schools: {stats[0]:,}\n"
        f"Total cities/districts: {stats[1]:,}\n"
        f"Total pincodes: {stats[2]:,}\n"
        f"Schools with detailed enrollment: {stats[3]:,}\n\n"
        "The database contains one deduplicated record per UDISE code, the main school "
        "summary, and available detailed enrollment data. Latitude and longitude have "
        "been removed. The attached .gz file can be decompressed to obtain the SQLite database.\n"
    )
    README.write_text(message, encoding="utf-8")
    print(message)
    print(f"SQLite: {OUTPUT} ({OUTPUT.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"Gzip:   {COMPRESSED} ({COMPRESSED.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
