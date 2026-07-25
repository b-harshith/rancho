#!/usr/bin/env python3
"""Build the canonical Bengaluru school-market datasets.

This build deliberately keeps school enrollment at the school/campus point.  It
does not allocate students to residential hexes.  Duplicate resolution is
conservative: Google Place IDs generate candidates, but never prove identity on
their own.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

import h3


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "new data" / "schools_geocoded.json"
DEFAULT_OUTPUT_DIR = ROOT / "src" / "public" / "data"

CENTRAL_LAT = 12.9716
CENTRAL_LON = 77.5946
H3_RESOLUTION = 7
BENGALURU_BOUNDS = (12.45, 13.50, 77.10, 78.10)

SENSITIVITY_THRESHOLDS = (175_000, 180_000, 200_000, 225_000, 250_000, 300_000, 500_000)
CAPTURE_RATES = (0.05, 0.10, 0.20, 1.00)
CENTER_CAPACITY = 200
TARGET_UTILIZATION = 0.80

NAME_STOPWORDS = {
    "school", "schools", "academy", "international", "public", "bengaluru",
    "bangalore", "residential", "the", "and", "campus", "branch",
}

OTHER_STATE_MARKERS = (
    "uttar pradesh", "maharashtra", "tamil nadu", "telangana", "kerala",
    "chhattisgarh", "delhi", "haryana", "rajasthan", "west bengal",
)


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def normalize_text(value: Any) -> str:
    text = html.unescape(str(value or "")).lower().replace("&", " and ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text)).strip()


def significant_name(value: Any) -> str:
    return " ".join(token for token in normalize_text(value).split() if token not in NAME_STOPWORDS)


def name_similarity(a: Any, b: Any) -> tuple[float, float]:
    left, right = significant_name(a), significant_name(b)
    if not left or not right:
        return 0.0, 0.0
    left_tokens, right_tokens = set(left.split()), set(right.split())
    jaccard = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    return jaccard, SequenceMatcher(None, left, right).ratio()


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    value = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def bearing_degrees(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlam = math.radians(lon2 - lon1)
    x = math.sin(dlam) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def classify_zone(lat: float, lon: float) -> str:
    if haversine_m(CENTRAL_LAT, CENTRAL_LON, lat, lon) <= 5_000:
        return "Central"
    names = ("North", "North-East", "East", "South-East", "South", "South-West", "West", "North-West")
    return names[int(((bearing_degrees(CENTRAL_LAT, CENTRAL_LON, lat, lon) + 22.5) % 360) // 45)]


def normalize_boards(raw: Any) -> list[str]:
    text = html.unescape(str(raw or "")).lower()
    values: list[str] = []

    def add(value: str) -> None:
        if value not in values:
            values.append(value)

    if "cbse" in text:
        add("cbse")
    if any(token in text for token in ("icse", "isc", "cisce")):
        add("cisce")
    if re.search(r"\bib\b", text):
        add("ib")
    if any(token in text for token in ("igcse", "cambridge", "cie")):
        add("cambridge")
    if "state board" in text:
        add("state")
    if "montessori" in text:
        add("montessori")
    if "nios" in text:
        add("nios")
    if "other board" in text:
        add("other")
    if "no board" in text:
        add("no_board")
    if not values:
        add("unknown")
    return values


def board_affiliation_status(raw: Any) -> str:
    return "proposed" if "to be affiliated" in str(raw or "").lower() else "current"


def valid_coordinates(row: dict[str, Any]) -> bool:
    lat, lon = as_float(row.get("lat"), math.nan), as_float(row.get("lon"), math.nan)
    min_lat, max_lat, min_lon, max_lon = BENGALURU_BOUNDS
    return math.isfinite(lat) and math.isfinite(lon) and min_lat <= lat <= max_lat and min_lon <= lon <= max_lon


def out_of_scope_address(row: dict[str, Any]) -> bool:
    address = normalize_text(row.get("google_formatted_address") or row.get("address"))
    return any(marker in address for marker in OTHER_STATE_MARKERS)


def area_compatible(a: dict[str, Any], b: dict[str, Any]) -> bool:
    left, right = normalize_text(a.get("area")), normalize_text(b.get("area"))
    unknown = {"", "unknown", "bengaluru", "bangalore", "bangalore rural"}
    if left in unknown or right in unknown:
        return True
    return left == right or SequenceMatcher(None, left, right).ratio() >= 0.82


def normalized_address_agreement(a: dict[str, Any], b: dict[str, Any]) -> bool:
    left = normalize_text(a.get("address") or a.get("google_formatted_address"))
    right = normalize_text(b.get("address") or b.get("google_formatted_address"))
    if not left or not right or left in {"na", "unknown"} or right in {"na", "unknown"}:
        return False
    return left == right or SequenceMatcher(None, left, right).ratio() >= 0.90


def locality_agreement(a: dict[str, Any], b: dict[str, Any]) -> bool:
    left = normalize_text(a.get("area") or a.get("google_locality"))
    right = normalize_text(b.get("area") or b.get("google_locality"))
    generic = {"", "unknown", "bengaluru", "bangalore", "bangalore rural"}
    if left in generic or right in generic:
        return False
    return left == right or SequenceMatcher(None, left, right).ratio() >= 0.82


def validated_same_school_place(a: dict[str, Any], b: dict[str, Any]) -> bool:
    place = str(a.get("google_place_id") or "").strip()
    if not place or place != str(b.get("google_place_id") or "").strip():
        return False
    if min(as_float(a.get("google_geocode_confidence")), as_float(b.get("google_geocode_confidence"))) < 0.80:
        return False
    if a.get("google_geocode_source") != "places_text_search" or b.get("google_geocode_source") != "places_text_search":
        return False
    education_types = {"school", "educational_institution", "primary_school", "secondary_school", "preschool", "kindergarten"}
    return bool(education_types & set(a.get("google_types") or [])) and bool(education_types & set(b.get("google_types") or []))


def source_distance_m(a: dict[str, Any], b: dict[str, Any]) -> float:
    alat = as_float(a.get("source_lat", a.get("lat")), math.nan)
    alon = as_float(a.get("source_lon", a.get("lon")), math.nan)
    blat = as_float(b.get("source_lat", b.get("lat")), math.nan)
    blon = as_float(b.get("source_lon", b.get("lon")), math.nan)
    if not all(math.isfinite(v) for v in (alat, alon, blat, blon)):
        return float("inf")
    return haversine_m(alat, alon, blat, blon)


def strong_entity_match(a: dict[str, Any], b: dict[str, Any]) -> bool:
    jaccard, sequence = name_similarity(a.get("name"), b.get("name"))
    strong_name = significant_name(a.get("name")) == significant_name(b.get("name")) or (jaccard >= 0.75 and sequence >= 0.80)
    if not strong_name:
        return False
    current_distance = haversine_m(as_float(a.get("lat")), as_float(a.get("lon")), as_float(b.get("lat")), as_float(b.get("lon")))
    coordinate_agreement = current_distance <= 50 and source_distance_m(a, b) <= 150
    return (
        validated_same_school_place(a, b)
        and normalized_address_agreement(a, b)
        and locality_agreement(a, b)
        and coordinate_agreement
    )


def stable_id(prefix: str, parts: Iterable[Any]) -> str:
    payload = "|".join(str(part) for part in parts)
    return f"{prefix}_{hashlib.sha1(payload.encode('utf-8')).hexdigest()[:14]}"


class UnionFind:
    def __init__(self, size: int, udise_sets: list[set[str]]) -> None:
        self.parent = list(range(size))
        self.udise_sets = [set(values) for values in udise_sets]

    def find(self, value: int) -> int:
        while self.parent[value] != value:
            self.parent[value] = self.parent[self.parent[value]]
            value = self.parent[value]
        return value

    def union_if_safe(self, a: int, b: int) -> bool:
        left, right = self.find(a), self.find(b)
        if left == right:
            return True
        combined = self.udise_sets[left] | self.udise_sets[right]
        if len(combined) > 1:
            return False
        if left > right:
            left, right = right, left
        self.parent[right] = left
        self.udise_sets[left] = combined
        return True


def resolve_entities(rows: list[dict[str, Any]]) -> tuple[list[list[int]], dict[int, list[str]], list[dict[str, Any]]]:
    quarantine: dict[int, list[str]] = defaultdict(list)
    for index, row in enumerate(rows):
        if not valid_coordinates(row):
            quarantine[index].append("invalid_or_out_of_bounds_coordinates")
        if out_of_scope_address(row):
            quarantine[index].append("google_address_outside_bengaluru_scope")
        board = str(row.get("board") or "").strip().lower()
        if "no board" in board or "no_board" in board:
            quarantine[index].append("no_board_quarantine")

    candidates: set[tuple[int, int]] = set()
    by_udise: dict[str, list[int]] = defaultdict(list)
    by_place: dict[str, list[int]] = defaultdict(list)
    by_name: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        udise = str(row.get("udise_code") or "").strip()
        if udise and udise.upper() != "NA":
            by_udise[udise].append(index)
        place = str(row.get("google_place_id") or "").strip()
        if place:
            by_place[place].append(index)
        by_name[significant_name(row.get("name"))].append(index)

    for indexes in by_udise.values():
        for a in indexes:
            for b in indexes:
                if a < b:
                    candidates.add((a, b))
    for groups in (by_place, by_name):
        for indexes in groups.values():
            if not indexes or len(indexes) > 30:
                continue
            for offset, a in enumerate(indexes):
                for b in indexes[offset + 1 :]:
                    if strong_entity_match(rows[a], rows[b]):
                        candidates.add((min(a, b), max(a, b)))

    # A listing without UDISE that strongly matches multiple distinct UDISE
    # entities is a bridge, not proof that those entities are one school.
    candidate_udises: dict[int, set[str]] = defaultdict(set)
    for a, b in candidates:
        for source, other in ((a, b), (b, a)):
            if not rows[source].get("udise_code") and rows[other].get("udise_code"):
                candidate_udises[source].add(str(rows[other]["udise_code"]))
    for index, codes in candidate_udises.items():
        if len(codes) > 1:
            quarantine[index].append("ambiguous_bridge_to_multiple_udise_entities")

    # Distinct UDISE codes with strong corroboration require manual review.
    ambiguous_groups: list[dict[str, Any]] = []
    for a, b in sorted(candidates):
        ua, ub = str(rows[a].get("udise_code") or ""), str(rows[b].get("udise_code") or "")
        if ua and ub and ua != ub:
            quarantine[a].append("ambiguous_distinct_udise_same_identity")
            quarantine[b].append("ambiguous_distinct_udise_same_identity")
            ambiguous_groups.append({"row_indexes": [a, b], "udise_codes": [ua, ub], "names": [rows[a].get("name"), rows[b].get("name")]})

    active = [index for index in range(len(rows)) if index not in quarantine]
    active_lookup = {old: new for new, old in enumerate(active)}
    udise_sets = []
    for old in active:
        code = str(rows[old].get("udise_code") or "").strip()
        udise_sets.append({code} if code else set())
    union = UnionFind(len(active), udise_sets)
    for a, b in sorted(candidates):
        if a in active_lookup and b in active_lookup:
            union.union_if_safe(active_lookup[a], active_lookup[b])

    groups: dict[int, list[int]] = defaultdict(list)
    for old in active:
        groups[union.find(active_lookup[old])].append(old)
    return sorted(groups.values(), key=lambda indexes: min(indexes)), quarantine, ambiguous_groups


def canonical_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def score(row: dict[str, Any]) -> tuple[float, int, float, str]:
        confidence = as_float(row.get("google_geocode_confidence"))
        udise = 1 if row.get("udise_code") else 0
        displacement = as_float(row.get("google_geocode_distance_m"), 99_999_999)
        return confidence, udise, -displacement, normalize_text(row.get("name"))
    return max(rows, key=score)


def make_entity(group: list[int], rows: list[dict[str, Any]]) -> dict[str, Any]:
    source_rows = [rows[index] for index in group]
    anchor = canonical_row(source_rows)
    udise_rows = [row for row in source_rows if row.get("enrollment_source") == "udise"]
    enrollment_row = max(udise_rows or source_rows, key=lambda row: as_float(row.get("students_grades_2_9")))
    lat, lon = as_float(anchor.get("lat")), as_float(anchor.get("lon"))
    raw_boards = sorted({str(row.get("board") or "unknown") for row in source_rows})
    boards: list[str] = []
    for raw in raw_boards:
        for board in normalize_boards(raw):
            if board not in boards:
                boards.append(board)
    identity_parts = sorted(
        f"{index}:{row.get('udise_code') or row.get('url') or f'{normalize_text(row.get("name"))}:{row.get("source_lat")}:{row.get("source_lon")}'}"
        for index, row in zip(group, source_rows)
    )
    fee_mins = [as_float(row.get("fee_min", row.get("fee"))) for row in source_rows]
    fee_maxes = [as_float(row.get("fee_max", row.get("fee"))) for row in source_rows]
    entity_id = stable_id("school", identity_parts)
    return {
        "school_entity_id": entity_id,
        "entity_id": entity_id,
        "name": anchor.get("name") or "Unknown school",
        "url": anchor.get("url") or "",
        "aliases": sorted({str(row.get("name") or "") for row in source_rows if row.get("name")}),
        "lat": lat,
        "lon": lon,
        "hex_id": h3.latlng_to_cell(lat, lon, H3_RESOLUTION),
        "zone": classify_zone(lat, lon),
        "area": anchor.get("area") or anchor.get("google_locality") or "Unknown",
        "address": anchor.get("google_formatted_address") or anchor.get("address") or "NA",
        "pincode": anchor.get("google_postal_code") or anchor.get("pincode") or "NA",
        "google_place_id": anchor.get("google_place_id"),
        "udise_codes": sorted({str(row.get("udise_code")) for row in source_rows if row.get("udise_code")}),
        "fee_min": min(fee_mins) if fee_mins else 0.0,
        "fee_max": max(fee_maxes) if fee_maxes else 0.0,
        "fee_basis": "annual_advertised_range",
        "boards": boards,
        "board_raw": raw_boards,
        "board_affiliation_status": "proposed" if any(board_affiliation_status(raw) == "proposed" for raw in raw_boards) else "current",
        "students_grades_2_9": as_float(enrollment_row.get("students_grades_2_9")),
        "students_total": as_float(enrollment_row.get("students_total")),
        "enrollment_source": "udise_backed" if udise_rows else "estimated",
        "grade_2_9_status": "positive" if as_float(enrollment_row.get("students_grades_2_9")) > 0 else "not_serving_or_unresolved",
        "structural_categories": sorted({str(row.get("structural_category") or "unknown") for row in source_rows}),
        "source_row_indexes": group,
        "source_row_count": len(group),
        "merge_status": "merged_duplicate_records" if len(group) > 1 else "single_record",
        "quartile": None,
        "q4_subquartile": None,
        "q4_segment": None,
    }


def group_campuses(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    union = UnionFind(len(entities), [set() for _ in entities])
    by_place: dict[str, list[int]] = defaultdict(list)
    for index, entity in enumerate(entities):
        if entity.get("google_place_id"):
            by_place[str(entity["google_place_id"])].append(index)
    for indexes in by_place.values():
        for offset, a in enumerate(indexes):
            for b in indexes[offset + 1 :]:
                ja, seq = name_similarity(entities[a]["name"], entities[b]["name"])
                close = haversine_m(entities[a]["lat"], entities[a]["lon"], entities[b]["lat"], entities[b]["lon"]) <= 50
                area_ok = area_compatible(entities[a], entities[b])
                if close and area_ok and (ja >= 0.50 or seq >= 0.70):
                    union.union_if_safe(a, b)

    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for index, entity in enumerate(entities):
        groups[union.find(index)].append(entity)

    campuses: list[dict[str, Any]] = []
    for members in groups.values():
        anchor = max(members, key=lambda entity: (entity["source_row_count"], entity["enrollment_source"] == "udise_backed", entity["name"]))
        member_ids = sorted(entity["school_entity_id"] for entity in members)
        boards = sorted({board for entity in members for board in entity["boards"]})
        # Campus grouping is conservative.  Co-located entity records often
        # represent the same school under a second listing or school-section
        # code, so summing would re-introduce the double count that campus
        # deduplication is meant to remove.  Prefer UDISE-backed evidence, then
        # retain the largest grade-2--9 enrollment within that source.
        udise_members = [entity for entity in members if entity["enrollment_source"] == "udise_backed"]
        enrollment_entity = max(udise_members or members, key=lambda entity: entity["students_grades_2_9"])
        enrollment = enrollment_entity["students_grades_2_9"]
        source_totals = {
            "udise_backed": enrollment if enrollment_entity["enrollment_source"] == "udise_backed" else 0.0,
            "estimated": enrollment if enrollment_entity["enrollment_source"] == "estimated" else 0.0,
        }
        campus_id = stable_id("campus", member_ids)
        campuses.append({
            "campus_id": campus_id,
            "name": anchor["name"],
            "url": anchor.get("url") or "",
            "school_entity_ids": member_ids,
            "entity_ids": member_ids,
            "entity_count": len(members),
            "lat": anchor["lat"],
            "lon": anchor["lon"],
            "hex_id": h3.latlng_to_cell(anchor["lat"], anchor["lon"], H3_RESOLUTION),
            "zone": classify_zone(anchor["lat"], anchor["lon"]),
            "area": anchor["area"],
            "address": anchor["address"],
            "google_place_id": anchor.get("google_place_id"),
            "fee_min": min(entity["fee_min"] for entity in members),
            "fee_max": max(entity["fee_max"] for entity in members),
            "boards": boards,
            "students_grades_2_9": enrollment,
            "enrollment_by_source": source_totals,
            "enrollment_school_entity_id": enrollment_entity["school_entity_id"],
            "enrollment_entity_id": enrollment_entity["entity_id"],
            "campus_enrollment_rule": "prefer_udise_then_largest_do_not_sum_colocated_entities",
            "grade_2_9_status": "positive" if enrollment > 0 else "not_serving_or_unresolved",
            "quartile": None,
            "q4_subquartile": None,
            "q4_segment": None,
        })
    return campuses


def assign_quartiles(records: list[dict[str, Any]]) -> None:
    """Assign fee quartiles to canonical school entities, never campuses."""
    def record_id(record: dict[str, Any]) -> str:
        return str(record.get("entity_id") or record.get("campus_id") or "")

    ordered = sorted(records, key=lambda record: (-record["fee_max"], -record["fee_min"], normalize_text(record["name"]), record_id(record)))
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


def enrollment_summary(entities: list[dict[str, Any]]) -> dict[str, Any]:
    positive = [entity for entity in entities if entity["students_grades_2_9"] > 0]
    source = {
        key: sum(entity["students_grades_2_9"] for entity in positive if entity["enrollment_source"] == key)
        for key in ("udise_backed", "estimated")
    }
    return {
        "school_entity_count_all": len(entities),
        "school_entity_count_grade_2_9_positive": len(positive),
        "campus_count_context": len({entity["campus_id"] for entity in entities}),
        "students_grades_2_9_expanded": round(sum(entity["students_grades_2_9"] for entity in positive), 2),
        "students_grades_2_9_by_source": {key: round(value, 2) for key, value in source.items()},
    }


def capacity_summary(students: float) -> list[dict[str, Any]]:
    effective_capacity = CENTER_CAPACITY * TARGET_UTILIZATION
    scenarios = []
    for rate in CAPTURE_RATES:
        captured = students * rate
        packed_full = math.floor(captured / CENTER_CAPACITY)
        residual = captured - packed_full * CENTER_CAPACITY
        minimum_required = math.ceil(captured / CENTER_CAPACITY) if captured else 0
        maximum_at_target = math.floor(captured / effective_capacity)
        utilization = captured / (minimum_required * CENTER_CAPACITY) if minimum_required else 0.0
        scenarios.append({
            "capture_rate": rate,
            "captured": round(captured, 2),
            "packed_full_centers": packed_full,
            "packed_residual": round(residual, 2),
            "minimum_centers_required": minimum_required,
            "maximum_centers_at_80pct": maximum_at_target,
            "utilization_at_minimum_centers": round(utilization, 6),
            "below_target_utilization": bool(minimum_required and utilization < TARGET_UTILIZATION),
        })
    return scenarios


def raw_preclean_benchmarks(rows: list[dict[str, Any]]) -> dict[str, Any]:
    raw_q4 = [row for row in rows if row.get("quartile analysis 1") == "Q4"]
    raw_q4_positive = [row for row in raw_q4 if as_float(row.get("students_grades_2_9")) > 0]
    sensitivity = []
    for threshold in (175_000, 180_000, 200_000):
        selected = [
            row for row in rows
            if as_float(row.get("fee_max", row.get("fee"))) >= threshold
            and as_float(row.get("students_grades_2_9")) > 0
        ]
        sensitivity.append({
            "threshold_fee_max": threshold,
            "positive_grade_2_9_row_count": len(selected),
            "students_grades_2_9_expanded": round(sum(as_float(row.get("students_grades_2_9")) for row in selected), 2),
            "description": "Raw pre-clean rows whose maximum fee reaches the cutoff; audit baseline only.",
        })
    return {
        "q4": {
            "row_count_all": len(raw_q4),
            "row_count_grade_2_9_positive": len(raw_q4_positive),
            "students_grades_2_9_expanded": round(sum(as_float(row.get("students_grades_2_9")) for row in raw_q4_positive), 2),
            "description": "Raw source-row Q4 benchmark before quarantine, duplicate collapse, and entity recomputation.",
        },
        "fee_max_sensitivity": sensitivity,
    }


def campus_context_summary(campuses: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "campus_count": len(campuses),
        "multi_entity_campus_count": sum(campus["entity_count"] > 1 for campus in campuses),
        "campus_count_grade_2_9_positive": sum(campus["students_grades_2_9"] > 0 for campus in campuses),
    }


def build_summary(entities: list[dict[str, Any]], campuses: list[dict[str, Any]]) -> dict[str, Any]:
    q4 = [entity for entity in entities if entity["quartile"] == "Q4"]
    q4_summary = enrollment_summary(q4)
    by_segment = {
        segment: enrollment_summary([entity for entity in q4 if entity["q4_segment"] == segment])
        for segment in ("Premium Elite", "Elite Luxury", "Super Luxury", "Ultra Luxury")
    }
    by_zone = {
        zone: enrollment_summary([entity for entity in q4 if entity["zone"] == zone])
        for zone in ("Central", "North", "North-East", "East", "South-East", "South", "South-West", "West", "North-West")
    }
    sensitivity = []
    for threshold in SENSITIVITY_THRESHOLDS:
        selected = [entity for entity in entities if entity["fee_max"] >= threshold]
        item = {"threshold_fee_max": threshold, **enrollment_summary(selected)}
        item["fee_range_crossing_entity_count"] = sum(entity["fee_min"] < threshold <= entity["fee_max"] for entity in selected)
        item["description"] = "Grade 2-9 enrollment associated with canonical school entities whose maximum fee reaches the cutoff."
        item["capacity"] = capacity_summary(item["students_grades_2_9_expanded"])
        sensitivity.append(item)
    return {
        "methodology": {
            "primary_cohort": "top floor(N/4) canonical school entities ranked by annual fee_max",
            "quartile_sort": ["fee_max_desc", "fee_min_desc", "normalized_name_asc", "entity_id_asc"],
            "sensitivity_basis": "canonical school entity fee_max >= inclusive threshold",
            "sensitivity_caveat": "Enrollment is associated with a qualifying school entity; it is not a count of students proven to pay the threshold fee.",
            "campus_enrollment_rule": "prefer UDISE-backed entity, then largest enrollment; never sum co-located entity records",
            "enrollment_sources": ["udise_backed", "estimated"],
            "center_capacity": CENTER_CAPACITY,
            "target_utilization": TARGET_UTILIZATION,
        },
        "all_school_entities": enrollment_summary(entities),
        "campus_map_context": campus_context_summary(campuses),
        "q4": {**q4_summary, "capacity": capacity_summary(q4_summary["students_grades_2_9_expanded"])},
        "q4_by_segment": by_segment,
        "q4_by_zone": by_zone,
        "fee_max_sensitivity": sensitivity,
    }


def build(input_path: Path, output_dir: Path) -> dict[str, Any]:
    rows = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise TypeError("School input must be a JSON array")

    # Estimate student counts for anomalous schools (grades 2-9 > 0 but total < 100)
    quartiles = ["Q1", "Q2", "Q3", "Q4"]
    per_class_averages = {q: [] for q in quartiles}
    for r in rows:
        board = str(r.get("board") or "").strip().lower()
        if "no board" in board or "no_board" in board:
            continue
        g29 = as_float(r.get("students_grades_2_9"))
        total = as_float(r.get("students_total"))
        q = r.get("quartile analysis 1")
        if q in quartiles and g29 > 0 and total >= 100:
            num_grades = 7 if r.get("structural_category") == "Primary / K-8" else 8
            per_class_averages[q].append(g29 / num_grades)
    
    q_averages = {}
    for q in quartiles:
        avgs = per_class_averages[q]
        q_averages[q] = sum(avgs) / len(avgs) if avgs else 50.0

    for r in rows:
        board = str(r.get("board") or "").strip().lower()
        if "no board" in board or "no_board" in board:
            continue
        g29 = as_float(r.get("students_grades_2_9"))
        total = as_float(r.get("students_total"))
        q = r.get("quartile analysis 1")
        if q in quartiles and g29 > 0 and total < 100:
            num_grades = 7 if r.get("structural_category") == "Primary / K-8" else 8
            est_g29 = round(q_averages[q] * num_grades)
            total_grades = 8 if r.get("structural_category") == "Primary / K-8" else (10 if r.get("structural_category") == "Secondary / K-10" else 12)
            est_total = round(q_averages[q] * total_grades)
            
            r["students_grades_2_9"] = est_g29
            r["students_total"] = est_total
            r["students"] = est_g29
            r["enrollment_source"] = "estimate"

    groups, quarantine, ambiguous_groups = resolve_entities(rows)
    entities = [make_entity(group, rows) for group in groups]
    campuses = group_campuses(entities)

    entity_to_campus = {entity_id: campus["campus_id"] for campus in campuses for entity_id in campus["school_entity_ids"]}
    for entity in entities:
        entity["campus_id"] = entity_to_campus[entity["school_entity_id"]]

    assign_quartiles(entities)
    q4_entity_ids = {entity["school_entity_id"] for entity in entities if entity["quartile"] == "Q4"}
    for campus in campuses:
        campus["q4_school_entity_ids"] = [entity_id for entity_id in campus["school_entity_ids"] if entity_id in q4_entity_ids]
        campus["q4_entity_ids"] = list(campus["q4_school_entity_ids"])
        campus["q4_entity_count"] = len(campus["q4_school_entity_ids"])
        campus["has_q4_entity"] = bool(campus["q4_school_entity_ids"])
    summary = build_summary(entities, campuses)

    q4 = [entity for entity in entities if entity["quartile"] == "Q4"]
    audit = {
        "input_path": str(input_path),
        "input_row_count": len(rows),
        "published_entity_count": len(entities),
        "published_campus_count": len(campuses),
        "duplicate_rows_collapsed": sum(entity["source_row_count"] - 1 for entity in entities),
        "multi_entity_campus_count": sum(campus["entity_count"] > 1 for campus in campuses),
        "quarantined_row_count": len(quarantine),
        "quarantined_rows": [
            {"row_index": index, "name": rows[index].get("name"), "reasons": sorted(set(reasons))}
            for index, reasons in sorted(quarantine.items())
        ],
        "ambiguous_identity_groups": ambiguous_groups,
        "raw_preclean_benchmarks": raw_preclean_benchmarks(rows),
        "q4": enrollment_summary(q4),
        "q4_fee_max_cutoff": min((entity["fee_max"] for entity in q4), default=None),
        "validation": {
            "source_rows_reconciled": len(rows) == sum(entity["source_row_count"] for entity in entities) + len(quarantine),
            "unique_entity_ids": len({entity["school_entity_id"] for entity in entities}) == len(entities),
            "entity_id_aliases_match": all(entity["school_entity_id"] == entity["entity_id"] for entity in entities),
            "unique_campus_ids": len({campus["campus_id"] for campus in campuses}) == len(campuses),
            "all_hexes_recomputed": all(entity["hex_id"] == h3.latlng_to_cell(entity["lat"], entity["lon"], H3_RESOLUTION) for entity in entities),
            "all_zones_assigned": all(entity["zone"] in {"Central", "North", "North-East", "East", "South-East", "South", "South-West", "West", "North-West"} for entity in entities),
            "q4_exact_floor_quarter": len(q4) == len(entities) // 4,
            "q4_subquartiles_reconcile": sum(entity["q4_subquartile"] is not None for entity in entities) == len(q4),
            "enrollment_source_reconciles": summary["q4"]["students_grades_2_9_expanded"] == round(sum(summary["q4"]["students_grades_2_9_by_source"].values()), 2),
            "sensitivity_monotonic": all(
                summary["fee_max_sensitivity"][index]["school_entity_count_all"] >= summary["fee_max_sensitivity"][index + 1]["school_entity_count_all"]
                and summary["fee_max_sensitivity"][index]["students_grades_2_9_expanded"] >= summary["fee_max_sensitivity"][index + 1]["students_grades_2_9_expanded"]
                for index in range(len(summary["fee_max_sensitivity"]) - 1)
            ),
        },
        "board_counts": dict(sorted(Counter(board for entity in entities for board in entity["boards"]).items())),
        "zone_counts": dict(sorted(Counter(entity["zone"] for entity in entities).items())),
    }
    if not all(audit["validation"].values()):
        failed = [key for key, value in audit["validation"].items() if not value]
        raise RuntimeError(f"School-market validation failed: {', '.join(failed)}")

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "school_entities.json": entities,
        "school_campuses.json": campuses,
        "school_market_summary.json": summary,
        "school_market_audit.json": audit,
    }
    for filename, payload in outputs.items():
        (output_dir / filename).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    audit = build(args.input, args.output_dir)
    print(json.dumps({key: audit[key] for key in ("input_row_count", "published_entity_count", "published_campus_count", "duplicate_rows_collapsed", "quarantined_row_count", "q4", "q4_fee_max_cutoff")}, indent=2))


if __name__ == "__main__":
    main()
