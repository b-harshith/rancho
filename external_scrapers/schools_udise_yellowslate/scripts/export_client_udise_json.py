#!/usr/bin/env python3
import gzip
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/client_export/udise_schools_client.sqlite3"
OUTPUT = ROOT / "data/client_export/udise_schools_client.json"
COMPRESSED = ROOT / "data/client_export/udise_schools_client.json.gz"


def parse_json(value):
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {"raw": value}


def main():
    db = sqlite3.connect(f"file:{SOURCE}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    metadata = {row["key"]: row["value"] for row in db.execute("SELECT key,value FROM metadata")}
    normalized_school_name = "LOWER(REPLACE(REPLACE(school_name,'-',' '),'&amp;','&'))"
    excluded_name = f"""(
        {normalized_school_name} LIKE '%preschool%' OR
        {normalized_school_name} LIKE '%pre school%' OR
        {normalized_school_name} LIKE '%playschool%' OR
        {normalized_school_name} LIKE '%play school%' OR
        (' ' || {normalized_school_name} || ' ') LIKE '% kids %' OR
        (' ' || {normalized_school_name} || ' ') LIKE '% kid %' OR
        {normalized_school_name} LIKE '%kidzee%' OR
        {normalized_school_name} LIKE '%kindergarten%' OR
        {normalized_school_name} LIKE '%kindergarden%' OR
        {normalized_school_name} LIKE '%daycare%' OR
        {normalized_school_name} LIKE '%day care%' OR
        {normalized_school_name} LIKE '%creche%' OR
        {normalized_school_name} LIKE '%toddler%' OR
        {normalized_school_name} LIKE '%early learning%' OR
        ({normalized_school_name} LIKE '%nursery%' AND
         {normalized_school_name} NOT LIKE '%primary%' AND
         {normalized_school_name} NOT LIKE '%elementary%' AND
         {normalized_school_name} NOT LIKE '%secondary%' AND
         {normalized_school_name} NOT LIKE '%high%' AND
         {normalized_school_name} NOT LIKE '%public%') OR
        {normalized_school_name} LIKE '%montessori%'
    )"""
    school_filter = (
        "COALESCE(CAST(json_extract(summary_json,'$.classTo') AS INTEGER),999) >= 2 "
        f"AND NOT {excluded_name} "
        "AND TRIM(json_extract(summary_json,'$.schMgmtDesc')) = 'Private Unaided (Recognized)' "
        "AND enrollment_json IS NOT NULL "
        "AND json_valid(enrollment_json) = 1 "
        "AND json_extract(enrollment_json,'$.status') = 1 "
        "AND json_type(enrollment_json,'$.data') = 'object'"
    )
    stats = db.execute(f"""SELECT COUNT(*),COUNT(DISTINCT district_name),COUNT(DISTINCT pincode),
        SUM(enrollment_json IS NOT NULL) FROM schools WHERE {school_filter}""").fetchone()
    metadata.update({
        "total_schools": str(stats[0]), "total_cities": str(stats[1]),
        "total_pincodes": str(stats[2]), "schools_with_enrollment": str(stats[3]),
        "grade_filter": "highest offered grade is Grade 2 or above",
        "institution_filter": "preschool, kids, daycare, play-school and equivalent names excluded",
        "management_filter": "Private Unaided (Recognized)",
        "enrollment_filter": "Valid successful enrollment response with data object",
    })

    with open(OUTPUT, "w", encoding="utf-8") as output:
        output.write('{"metadata":')
        json.dump(metadata, output, ensure_ascii=False, separators=(",", ":"))
        output.write(',"schools":[')
        first = True
        for count, row in enumerate(db.execute(
            f"SELECT * FROM schools WHERE {school_filter} ORDER BY udise_code"
        ), 1):
            record = {
                "udise_code": row["udise_code"],
                "school_id": row["school_id"],
                "year_id": row["year_id"],
                "school_name": row["school_name"],
                "pincode": row["pincode"],
                "state_name": row["state_name"],
                "district_name": row["district_name"],
                "summary": parse_json(row["summary_json"]),
                "enrollment": parse_json(row["enrollment_json"]),
            }
            if not first:
                output.write(",")
            json.dump(record, output, ensure_ascii=False, separators=(",", ":"))
            first = False
            if count % 5000 == 0:
                print(f"Exported {count:,} schools...", flush=True)
        output.write("]}\n")
    db.close()

    with open(OUTPUT, "rb") as source, gzip.open(COMPRESSED, "wb", compresslevel=9) as target:
        while chunk := source.read(1024 * 1024):
            target.write(chunk)

    print(f"JSON: {OUTPUT} ({OUTPUT.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"Gzip: {COMPRESSED} ({COMPRESSED.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
