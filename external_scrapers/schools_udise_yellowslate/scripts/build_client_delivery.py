#!/usr/bin/env python3
import csv
import json
import shutil
import re
from pathlib import Path

from scripts.filter_grade2_plus_exports import preschool_or_kids

ROOT = Path(__file__).resolve().parents[1]
SOURCE_CSV = ROOT / "data/client_export/ezy_yellowslate_unified_all_cities_geocoded.csv"
CAMPUSES = ROOT / "data/client_export/school_campuses.json"
BANGALORE_CAMPUSES = Path("/Users/malleswararao/Desktop/BangaloreRancho/web_platform_vercel_exact_latest/src/public/data/school_campuses.json")
BANGALORE_ENTITIES = Path("/Users/malleswararao/Desktop/BangaloreRancho/web_platform_vercel_exact_latest/src/public/data/school_entities.json")
SOURCE_UDISE = ROOT / "data/client_export/udise_schools_client.json"
DELIVERY = ROOT / "data/client_delivery"
OUTPUT_CSV = DELIVERY / "schools_geocoded_unified_with_campuses.csv"
OUTPUT_UDISE = DELIVERY / "udise_private_unaided_with_enrollment.csv"

CAMPUS_COLUMNS = [
    "city_rank_by_q4_count", "city_q4_campus_count", "city_preference_rank",
    "campus_id", "campus_entity_count", "campus_hex_id", "campus_zone",
    "campus_fee_min", "campus_fee_max", "campus_students_grades_2_9",
    "campus_enrollment_udise_backed", "campus_enrollment_estimated",
    "campus_enrollment_rule", "fee_quartile", "q4_subquartile",
    "q4_segment", "has_q4_entity",
]


def assign_quartiles(records):
    ordered = sorted(records, key=lambda row: (
        -float(row.get("fee_max") or 0), -float(row.get("fee_min") or 0),
        (row.get("name") or "").lower(), row.get("campus_id") or "",
    ))
    q4_size = len(ordered) // 4
    for index, campus in enumerate(ordered):
        if index < q4_size:
            campus["quartile"] = "Q4"
        else:
            remaining = len(ordered) - q4_size
            bucket = min(2, ((index - q4_size) * 3) // max(remaining, 1))
            campus["quartile"] = ("Q3", "Q2", "Q1")[bucket]
    q4 = ordered[:q4_size]; base = len(q4) // 4
    for index, campus in enumerate(q4):
        if index < base:
            campus["q4_subquartile"], campus["q4_segment"] = "Q4-Sub-Q4", "Ultra Luxury"
        elif index < base * 2:
            campus["q4_subquartile"], campus["q4_segment"] = "Q4-Sub-Q3", "Super Luxury"
        elif index < base * 3:
            campus["q4_subquartile"], campus["q4_segment"] = "Q4-Sub-Q2", "Elite Luxury"
        else:
            campus["q4_subquartile"], campus["q4_segment"] = "Q4-Sub-Q1", "Premium Elite"
    for campus in ordered:
        campus["has_q4_entity"] = campus["quartile"] == "Q4"


def main():
    DELIVERY.mkdir(parents=True, exist_ok=True)
    # Do not leave stale deliverables: this folder intentionally has two files.
    for path in DELIVERY.iterdir():
        if path.is_file():
            path.unlink()

    campuses = json.loads(CAMPUSES.read_text(encoding="utf-8"))
    bangalore_raw = json.loads(BANGALORE_CAMPUSES.read_text(encoding="utf-8"))
    bangalore_entities = json.loads(BANGALORE_ENTITIES.read_text(encoding="utf-8"))
    bangalore_entity_by_id = {
        str(entity.get("school_entity_id") or entity.get("entity_id")): entity
        for entity in bangalore_entities
    }
    bangalore = []
    for campus in bangalore_raw:
        if preschool_or_kids({"school_name": campus.get("name"), "udise_code": ""}):
            continue
        campus = dict(campus)
        campus["city"] = "bangalore"
        bangalore.append(campus)
    assign_quartiles(bangalore)
    campuses.extend(bangalore)
    by_campus_id = {str(c.get("campus_id") or ""): c for c in campuses if c.get("campus_id")}
    by_place = {str(c.get("google_place_id") or ""): c for c in campuses if c.get("google_place_id")}
    city_q4_counts = {}
    for campus in campuses:
        if campus.get("quartile") == "Q4":
            city = campus.get("city") or ""
            city_q4_counts[city] = city_q4_counts.get(city, 0) + 1
    ranked_cities = sorted(city_q4_counts, key=lambda city: (-city_q4_counts[city], city))
    city_q4_ranks = {city: rank for rank, city in enumerate(ranked_cities, 1)}

    with open(SOURCE_CSV, encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        fields = list(reader.fieldnames or []) + CAMPUS_COLUMNS
        rows = list(reader)

    # Bangalore arrives as an already-deduplicated campus dataset. Represent
    # each campus as one unified school row and preserve its existing campus ID.
    for campus in bangalore:
        entity_id = str(
            campus.get("enrollment_school_entity_id")
            or campus.get("enrollment_entity_id")
            or next(iter(campus.get("school_entity_ids") or []), "")
        )
        entity = bangalore_entity_by_id.get(entity_id, {})
        name = str(campus.get("name") or "").strip()
        url = str(campus.get("url") or "").strip()
        address = str(entity.get("address") or campus.get("address") or "").strip()
        pin_match = re.search(r"\b(\d{6})\b", address)
        pincode = str(entity.get("pincode") or (pin_match.group(1) if pin_match else ""))
        source_name = "yellowslate" if "yellowslate" in url else "ezyschooling" if "ezyschooling" in url else "bangalore_campus_file"
        source_totals = campus.get("enrollment_by_source") or {}
        udise_codes = [str(code) for code in (entity.get("udise_codes") or []) if code]
        matched = bool(udise_codes) or float(source_totals.get("udise_backed") or 0) > 0
        structural = "|".join(str(value) for value in (entity.get("structural_categories") or []) if value)
        rows.append({
            "campus_id": campus.get("campus_id"),
            "school_name": name,
            "normalized_name": re.sub(r"[^a-z0-9]", "", name.lower()),
            "city": "bangalore", "area": campus.get("area") or "", "address": address,
            "pincode": pincode,
            "latitude": campus.get("lat"), "longitude": campus.get("lon"),
            "coordinate_source": "existing_google_place", "boards": "|".join(campus.get("boards") or []),
            "fee": campus.get("fee_max"), "fee_min": campus.get("fee_min"), "fee_max": campus.get("fee_max"),
            "fee_text": "", "lowest_class": "", "highest_class": "", "offered_classes": structural,
            "student_enrollment": entity.get("students_total") or "",
            "student_enrollment_grades_2_9": entity.get("students_grades_2_9") or campus.get("students_grades_2_9") or 0,
            "enrollment_source": "UDISE" if matched else str(entity.get("enrollment_source") or "Estimated").title(),
            "udise_code": "|".join(udise_codes), "udise_school_name": "",
            "match_status": "matched" if matched else "unmatched",
            "ezyschooling_url": url if source_name == "ezyschooling" else "",
            "yellowslate_url": url if source_name == "yellowslate" else "", "primary_url": url,
            "source": source_name, "source_cities": "bangalore", "category": structural, "zone": entity.get("zone") or campus.get("zone") or "",
            "data_quality_notes": "imported_from_bangalore_school_campuses_and_entities",
            "google_formatted_address": address, "google_place_id": campus.get("google_place_id") or "",
            "google_location_type": "", "google_partial_match": "", "google_result_types": "school",
            "google_viewport_json": "", "google_geocode_query": "", "google_geocode_status": "existing",
            "google_used_fallback_query": "", "geocode_confidence": "existing_place_id",
            "school_type_rerun_status": "not_required", "school_type_rerun_query": "",
            "school_type_original_result_types": "school", "school_type_rerun_replaced": "false",
        })

    missing_campus = 0
    for row in rows:
        campus = by_campus_id.get(row.get("campus_id", "")) or by_place.get(row.get("google_place_id", ""))
        if not campus:
            missing_campus += 1
            continue
        source_totals = campus.get("enrollment_by_source") or {}
        row.update({
            "campus_id": campus.get("campus_id"),
            "campus_entity_count": campus.get("entity_count"),
            "campus_hex_id": campus.get("hex_id"),
            "campus_zone": campus.get("zone"),
            "campus_fee_min": campus.get("fee_min"),
            "campus_fee_max": campus.get("fee_max"),
            "campus_students_grades_2_9": campus.get("students_grades_2_9"),
            "campus_enrollment_udise_backed": source_totals.get("udise_backed"),
            "campus_enrollment_estimated": source_totals.get("estimated"),
            "campus_enrollment_rule": campus.get("campus_enrollment_rule"),
            "fee_quartile": campus.get("quartile"),
            "q4_subquartile": campus.get("q4_subquartile"),
            "q4_segment": campus.get("q4_segment"),
            "has_q4_entity": campus.get("has_q4_entity"),
        })

    def numeric(value):
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    rows.sort(key=lambda row: (
        city_q4_ranks.get(row.get("city", ""), 999),
        row.get("city", ""),
        0 if row.get("match_status") == "matched" else 1,
        -numeric(row.get("campus_fee_max") or row.get("fee_max") or row.get("fee")),
        -numeric(row.get("campus_students_grades_2_9") or row.get("student_enrollment_grades_2_9")),
        (row.get("school_name") or "").lower(),
    ))
    city_rank = {}
    for row in rows:
        city = row.get("city", "")
        city_rank[city] = city_rank.get(city, 0) + 1
        row["city_rank_by_q4_count"] = city_q4_ranks.get(city, "")
        row["city_q4_campus_count"] = city_q4_counts.get(city, 0)
        row["city_preference_rank"] = city_rank[city]

    with open(OUTPUT_CSV, "w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    udise_document = json.loads(SOURCE_UDISE.read_text(encoding="utf-8"))
    udise_columns = [
        "udise_code", "school_id", "year_id", "school_name", "pincode",
        "state_name", "district_name", "summary_json", "enrollment_json",
    ]
    with open(OUTPUT_UDISE, "w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=udise_columns)
        writer.writeheader()
        for school in udise_document.get("schools", []):
            writer.writerow({
                "udise_code": school.get("udise_code"),
                "school_id": school.get("school_id"),
                "year_id": school.get("year_id"),
                "school_name": school.get("school_name"),
                "pincode": school.get("pincode"),
                "state_name": school.get("state_name"),
                "district_name": school.get("district_name"),
                "summary_json": json.dumps(school.get("summary"), ensure_ascii=False, separators=(",", ":")),
                "enrollment_json": json.dumps(school.get("enrollment"), ensure_ascii=False, separators=(",", ":")),
            })
    print(f"Unified rows: {len(rows):,}")
    print(f"Rows without campus mapping: {missing_campus:,}")
    print(f"Delivery folder: {DELIVERY}")


if __name__ == "__main__":
    main()
