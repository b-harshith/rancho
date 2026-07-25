#!/usr/bin/env python3
import csv
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

import h3

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data/client_export/ezy_yellowslate_unified_all_cities_geocoded.csv"
OUTPUT = ROOT / "data/client_export/school_campuses.json"


def stable_id(prefix, *parts):
    value = "|".join(str(part or "").strip().lower() for part in parts)
    return f"{prefix}_{hashlib.sha256(value.encode()).hexdigest()[:14]}"


def number(value):
    try:
        return float(value) if str(value).strip() else None
    except (TypeError, ValueError):
        return None


def normalize_board(board):
    board = re.sub(r"\s+board$", "", board.strip().lower())
    aliases = {"cie": "cambridge", "igcse": "cambridge", "state": "state board"}
    return aliases.get(board, board)


def assign_city_quartiles(campuses):
    """Apply the Bangalore fee_max methodology independently within each city."""
    by_city = defaultdict(list)
    for campus in campuses:
        by_city[campus["city"]].append(campus)

    for city_campuses in by_city.values():
        ordered = sorted(
            city_campuses,
            key=lambda row: (
                -(row.get("fee_max") or 0), -(row.get("fee_min") or 0),
                (row.get("name") or "").lower(), row["campus_id"],
            ),
        )
        q4_size = len(ordered) // 4
        for index, campus in enumerate(ordered):
            if index < q4_size:
                campus["quartile"] = "Q4"
            else:
                remaining = len(ordered) - q4_size
                bucket = min(2, ((index - q4_size) * 3) // max(remaining, 1))
                campus["quartile"] = ("Q3", "Q2", "Q1")[bucket]

        q4 = ordered[:q4_size]
        base = len(q4) // 4
        boundaries = (base, base * 2, base * 3)
        for index, campus in enumerate(q4):
            if index < boundaries[0]:
                sub, segment = "Q4-Sub-Q4", "Ultra Luxury"
            elif index < boundaries[1]:
                sub, segment = "Q4-Sub-Q3", "Super Luxury"
            elif index < boundaries[2]:
                sub, segment = "Q4-Sub-Q2", "Elite Luxury"
            else:
                sub, segment = "Q4-Sub-Q1", "Premium Elite"
            campus["q4_subquartile"] = sub
            campus["q4_segment"] = segment


def main():
    with open(INPUT, encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))

    entities = []
    for row in rows:
        lat, lon = number(row.get("latitude")), number(row.get("longitude"))
        if lat is None or lon is None:
            continue
        entity_id = stable_id(
            "school", row.get("udise_code") or row.get("normalized_name"),
            row.get("city"), row.get("pincode"), row.get("area"),
        )
        entities.append((row, lat, lon, entity_id))

    # A Google place ID is the strongest campus key. Otherwise use coordinates
    # rounded to about 11 metres, keeping unrelated nearby schools separate by name.
    groups = defaultdict(list)
    for row, lat, lon, entity_id in entities:
        place_id = row.get("google_place_id", "").strip()
        key = ("place", place_id) if place_id else (
            "coordinate", round(lat, 4), round(lon, 4), row.get("normalized_name", "")
        )
        groups[key].append((row, lat, lon, entity_id))

    campuses = []
    for key, members in groups.items():
        # Prefer UDISE-backed enrollment; otherwise choose the largest estimate.
        def enrollment_rank(member):
            row = member[0]
            is_udise = (row.get("enrollment_source") or "").strip().lower() == "udise"
            return is_udise, number(row.get("student_enrollment_grades_2_9")) or 0

        selected = max(members, key=enrollment_rank)
        row, lat, lon, selected_entity_id = selected
        entity_ids = sorted(member[3] for member in members)
        students = number(row.get("student_enrollment_grades_2_9")) or 0.0
        udise_backed = (row.get("enrollment_source") or "").strip().lower() == "udise"
        boards = sorted({
            normalize_board(board)
            for member in members
            for board in (member[0].get("boards") or "").split("|")
            if board.strip()
        })
        place_id = row.get("google_place_id", "").strip() or None
        campus_id = stable_id("campus", place_id or key, *entity_ids)
        campuses.append({
            "campus_id": campus_id,
            "name": row.get("school_name"),
            "city": row.get("city"),
            "url": row.get("primary_url") or row.get("yellowslate_url") or row.get("ezyschooling_url"),
            "school_entity_ids": entity_ids,
            "entity_ids": entity_ids,
            "entity_count": len(entity_ids),
            "lat": lat,
            "lon": lon,
            "hex_id": h3.latlng_to_cell(lat, lon, 7),
            "zone": row.get("zone") or None,
            "area": row.get("area") or None,
            "address": row.get("google_formatted_address") or row.get("address") or None,
            "google_place_id": place_id,
            "google_location_type": row.get("google_location_type") or None,
            "google_partial_match": row.get("google_partial_match") == "true",
            "geocode_confidence": row.get("geocode_confidence") or None,
            "fee_min": number(row.get("fee_min")),
            "fee_max": number(row.get("fee_max")),
            "boards": boards,
            "students_grades_2_9": students,
            "enrollment_by_source": {
                "udise_backed": students if udise_backed else 0.0,
                "estimated": 0.0 if udise_backed else students,
            },
            "enrollment_school_entity_id": selected_entity_id,
            "enrollment_entity_id": selected_entity_id,
            "campus_enrollment_rule": "prefer_udise_then_largest_do_not_sum_colocated_entities",
            "grade_2_9_status": "positive" if students > 0 else "missing_or_zero",
            "quartile": None,
            "q4_subquartile": None,
            "q4_segment": None,
            "q4_school_entity_ids": entity_ids,
            "q4_entity_ids": entity_ids,
            "q4_entity_count": len(entity_ids),
            "has_q4_entity": bool(entity_ids),
        })

    assign_city_quartiles(campuses)
    for campus in campuses:
        if campus["quartile"] != "Q4":
            campus["q4_school_entity_ids"] = []
            campus["q4_entity_ids"] = []
            campus["q4_entity_count"] = 0
            campus["has_q4_entity"] = False
    campuses.sort(key=lambda item: (-(item["students_grades_2_9"] or 0), item["name"] or ""))
    OUTPUT.write_text(json.dumps(campuses, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Input schools with coordinates: {len(entities):,}")
    print(f"Output campuses: {len(campuses):,}")
    print(f"Output: {OUTPUT}")


if __name__ == "__main__":
    main()
