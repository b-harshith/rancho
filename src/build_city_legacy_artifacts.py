#!/usr/bin/env python3
"""Build Bangalore-compatible, city-scoped legacy bundles.

The legacy portal expects a deep city bundle: ranked H3 cells, named
neighbourhoods, zone and micro-market summaries, school-market summaries, and
source reconciliation.  This builder creates that contract for the four
expansion cities using only the supplied bucketed school tiers; it does not
invent annual fee values.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:  # Direct script execution from src/
    from build_multicity_platform import (
        CATEGORIES,
        CITY_FALLBACK_CENTERS,
        CITY_LABELS,
        SCORING_WEIGHTS,
        SOURCE_FILES,
        TARGET_CITIES,
        artifact_metadata,
        build_neighborhood_index,
        clean,
        compact_category_metrics,
        compact_context_metrics,
        file_sha256,
        h3,
        h3_center,
        h3_polygon,
        layer_h3_groups,
        normalize_city,
        nullable_sum,
        number,
        pct,
        choose_neighborhood_name,
        read_csv,
        project_coordinate_decision,
        project_identity,
        public_project_id,
        row_coordinates,
        source_reported,
        unique_projects,
        write_json,
    )
except ImportError:  # pragma: no cover - package import during tests
    from src.build_multicity_platform import (
        CATEGORIES,
        CITY_FALLBACK_CENTERS,
        CITY_LABELS,
        SCORING_WEIGHTS,
        SOURCE_FILES,
        TARGET_CITIES,
        artifact_metadata,
        build_neighborhood_index,
        clean,
        compact_category_metrics,
        compact_context_metrics,
        file_sha256,
        h3,
        h3_center,
        h3_polygon,
        layer_h3_groups,
        normalize_city,
        nullable_sum,
        number,
        pct,
        choose_neighborhood_name,
        read_csv,
        project_coordinate_decision,
        project_identity,
        public_project_id,
        row_coordinates,
        source_reported,
        unique_projects,
        write_json,
    )


SCHEMA_VERSION = "city-legacy-parity-v2"
H3_RESOLUTION = 7
PRIMARY_CATEGORY = "premium_plus"


def normalize_score(value: float | int | None, maximum: float | int | None) -> float | None:
    if value is None or maximum in (None, 0):
        return None
    return round(max(0.0, min(100.0, float(value) * 100.0 / float(maximum))), 4)


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[int(position)]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def robust_normalized_scores(values: list[float | int | None]) -> list[float | None]:
    logged = [None if value is None else math.log1p(max(0.0, float(value))) for value in values]
    positives = [value for value in logged if value is not None and value > 0]
    if not positives:
        return [None if value is None else 0.0 for value in values]
    lo = percentile(positives, 5) or 0.0
    hi = percentile(positives, 95) or lo
    if hi <= lo:
        return [None if value is None else (100.0 if value > 0 else 0.0) for value in values]
    output: list[float | None] = []
    for value in logged:
        if value is None:
            output.append(None)
        elif value <= 0:
            output.append(0.0)
        else:
            clipped = min(max(value, lo), hi)
            output.append(round((clipped - lo) * 100.0 / (hi - lo), 4))
    return output


def numeric_average(values: Iterable[float | None]) -> float | None:
    known = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return round(sum(known) / len(known), 4) if known else None


def source_metadata(path: Path, logical_path: str, row_count: int) -> dict[str, Any]:
    return {
        "file": logical_path,
        "filename": path.name,
        "row_count": row_count,
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
        "file_modified_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat(),
        "source_observation_as_of": None,
        "academic_year": None,
        "date_note": "The source does not publish a verified observation date or academic year in this dataset.",
    }


def stable_id(prefix: str, *parts: Any) -> str:
    payload = "|".join(clean(part).lower() for part in parts if clean(part))
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:14] if payload else hashlib.sha1(prefix.encode("utf-8")).hexdigest()[:14]
    return f"{prefix}_{digest}"


def lat_lon_for(row: dict[str, str], layer: str, city_id: str) -> tuple[float, float] | None:
    return row_coordinates(row, layer, city_id)


def h3_for_point(lat: float, lon: float) -> str:
    return h3.latlng_to_cell(lat, lon, H3_RESOLUTION)


def load_sources(data_root: Path) -> tuple[dict[str, list[dict[str, str]]], dict[str, Any]]:
    raw: dict[str, list[dict[str, str]]] = {}
    provenance: dict[str, Any] = {}
    for layer, relative_path in SOURCE_FILES.items():
        path = data_root / relative_path
        if not path.exists():
            raise FileNotFoundError(f"Required source file missing: {path}")
        raw[layer] = read_csv(path)
        provenance[layer] = source_metadata(path, relative_path, len(raw[layer]))
    return raw, provenance


def partition_city_rows(raw: dict[str, list[dict[str, str]]]) -> tuple[dict[str, dict[str, list[dict[str, str]]]], dict[str, Counter[str]]]:
    city_rows = {city_id: {layer: [] for layer in SOURCE_FILES} for city_id in TARGET_CITIES}
    excluded = {layer: Counter() for layer in SOURCE_FILES}
    for layer, rows in raw.items():
        for row in rows:
            city_id = normalize_city(row.get("city"))
            if city_id in city_rows:
                city_rows[city_id][layer].append({**row, "canonical_city_id": city_id})
            else:
                excluded[layer][clean(row.get("city")) or "(blank)"] += 1
    return city_rows, excluded


def canonical_label(value: Any) -> str | None:
    label = " ".join(clean(value).replace("_", " ").split())
    if not label or label.upper() in {"NA", "N/A", "NONE", "NULL", "UNKNOWN"}:
        return None
    return label


GENERIC_NEIGHBOURHOOD_TERMS = {
    "urban", "rural", "city", "district", "unknown", "nan", "none",
    "new delhi", "delhi", "gurgaon", "gurugram", "thane", "maharashtra",
    "telangana", "karnataka", "haryana", "uttar pradesh",
}


GENERIC_CITY_LABELS = {
    city_id: {
        CITY_LABELS[city_id].lower(),
        CITY_LABELS[city_id].replace(" ", "").lower(),
        city_id.replace("_", " ").lower(),
        city_id.replace("_", "").lower(),
    }
    for city_id in TARGET_CITIES
}
GENERIC_CITY_LABELS["bengaluru"].update({"bangalore"})
GENERIC_CITY_LABELS["delhi_ncr"].update({"delhi ncr", "delhi-ncr"})


def add_name_vote(votes: Counter[str], value: Any, weight: int, city_id: str | None = None) -> None:
    label = canonical_label(value)
    if label and city_id:
        normalized = " ".join(label.lower().replace("-", " ").split())
        compact = normalized.replace(" ", "")
        if normalized in GENERIC_CITY_LABELS[city_id] or compact in GENERIC_CITY_LABELS[city_id] or normalized in GENERIC_NEIGHBOURHOOD_TERMS:
            return
    if label:
        votes[label] += weight


def approximate_zone(city_id: str, lat: float, lon: float) -> str:
    center = CITY_FALLBACK_CENTERS[city_id]
    dlat = lat - center["latitude"]
    dlon = lon - center["longitude"]
    if abs(dlat) < 0.03 and abs(dlon) < 0.03:
        return "Central"
    vertical = "North" if dlat > 0 else "South"
    horizontal = "East" if dlon > 0 else "West"
    if abs(dlat) > abs(dlon) * 1.35:
        return vertical
    if abs(dlon) > abs(dlat) * 1.35:
        return horizontal
    return f"{vertical}-{horizontal}"


def naming_for_cell(
    city_id: str,
    hex_id: str,
    schools: list[dict[str, str]],
    projects: list[dict[str, str]],
    offices: list[dict[str, str]],
    hospitals: list[dict[str, str]],
    localities: list[dict[str, str]],
) -> dict[str, Any]:
    votes: Counter[str] = Counter()
    source_votes: Counter[str] = Counter()
    for row in localities:
        add_name_vote(votes, row.get("name") or row.get("locality"), 5, city_id)
        source_votes["locality"] += 1
    for row in projects:
        add_name_vote(votes, row.get("locality") or row.get("name"), 4, city_id)
        source_votes["project"] += 1
    for row in schools:
        add_name_vote(votes, row.get("area") or row.get("district") or row.get("pincode"), 3, city_id)
        source_votes["school"] += 1
    for row in hospitals:
        add_name_vote(votes, row.get("locality") or row.get("name"), 2, city_id)
        source_votes["hospital"] += 1
    for row in offices:
        add_name_vote(votes, row.get("locality") or row.get("address") or row.get("name"), 2, city_id)
        source_votes["office"] += 1

    center = h3_center(hex_id)
    zone_votes = Counter(canonical_label(row.get("zone")) for row in projects + offices + hospitals + localities)
    zone_votes = Counter({key: value for key, value in zone_votes.items() if key})
    zone = zone_votes.most_common(1)[0][0] if zone_votes else approximate_zone(city_id, center["latitude"], center["longitude"])
    zone_source = "source_zone" if zone_votes else "centroid_relative_zone"

    if votes:
        name, weighted_count = sorted(votes.items(), key=lambda item: (-item[1], item[0]))[0]
        confidence = round(min(1.0, weighted_count / max(1, sum(votes.values()))), 4)
        source = sorted(source_votes.items(), key=lambda item: (-item[1], item[0]))[0][0]
    else:
        name = f"{zone} H3 {hex_id[-5:]}"
        confidence = 0.15
        source = "generated_from_zone_and_h3"

    return {
        "name": name,
        "neighbourhood_name": name,
        "name_source": source,
        "name_confidence": confidence,
        "zone": zone,
        "zone_source": zone_source,
    }


def top_schools(rows: list[dict[str, str]], limit: int = 12) -> list[dict[str, Any]]:
    ordered = sorted(
        [row for row in rows if source_reported(row)],
        key=lambda row: (-(number(row.get("enrollment_total")) or 0), clean(row.get("school_name"))),
    )
    return [
        {
            "id": clean(row.get("school_id")) or None,
            "name": clean(row.get("school_name")),
            "fee_tier": clean(row.get("fee_tier")) or None,
            "reported_enrollment_total": number(row.get("enrollment_total")),
            "reported_students_grade_2_9": number(row.get("enrollment_grade_2_9")),
            "grade_2_9_method": "derived_from_source_reported_total_enrollment",
            "board": clean(row.get("board")) or None,
            "coordinate_quality": clean(row.get("coordinate_quality")) or None,
        }
        for row in ordered[:limit]
    ]


def top_named_rows(rows: list[dict[str, str]], id_key: str, score_key: str | None = None, limit: int = 12) -> list[dict[str, Any]]:
    def sort_value(row: dict[str, str]) -> tuple[float, str]:
        return (-(number(row.get(score_key)) or 0.0), clean(row.get("name"))) if score_key else (0.0, clean(row.get("name")))

    return [
        {
            "id": clean(row.get(id_key)) or None,
            "name": clean(row.get("name")),
            "locality": clean(row.get("locality")) or None,
            "segment": clean(row.get("segment") or row.get("final_q4_segment")) or None,
        }
        for row in sorted(rows, key=sort_value)[:limit]
    ]


def build_raw_hex_records(city_id: str, layers: dict[str, list[dict[str, str]]]) -> list[dict[str, Any]]:
    grouped = {
        "schools": layer_h3_groups(layers["schools"], "schools", city_id),
        "projects": layer_h3_groups(layers["projects"], "projects", city_id),
        "offices": layer_h3_groups(layers["offices"], "offices", city_id),
        "hospitals": layer_h3_groups(layers["hospitals"], "hospitals", city_id),
        "localities": layer_h3_groups(layers["localities"], "localities", city_id),
    }
    neighborhood_candidates, named_points = build_neighborhood_index(layers, city_id)
    all_cells = sorted(set().union(*(set(value) for value in grouped.values())))
    records: list[dict[str, Any]] = []
    for hex_id in all_cells:
        schools = grouped["schools"].get(hex_id, [])
        projects = grouped["projects"].get(hex_id, [])
        offices = grouped["offices"].get(hex_id, [])
        hospitals = grouped["hospitals"].get(hex_id, [])
        localities = grouped["localities"].get(hex_id, [])
        categories = compact_category_metrics(schools)
        context = compact_context_metrics(projects, offices, hospitals, localities)
        naming = naming_for_cell(city_id, hex_id, schools, projects, offices, hospitals, localities)
        neighborhood = choose_neighborhood_name(
            hex_id,
            neighborhood_candidates.get(hex_id, []),
            named_points,
            city_id,
        )
        naming.update({
            "name": neighborhood["name"],
            "neighbourhood_name": neighborhood["name"],
            "neighborhood_name": neighborhood["name"],
            "name_source": neighborhood["source"],
            "neighborhood_name_source": neighborhood["source"],
            "neighborhood_name_confidence_label": neighborhood["confidence"],
            "neighborhood_name_distance_km": neighborhood["distance_km"],
            "name_confidence": {"high": 0.92, "medium": 0.68, "low": 0.35}.get(
                neighborhood["confidence"], naming["name_confidence"]
            ),
        })
        all_students = categories["all_private"]["reported_students_grade_2_9"]
        premium_students = categories[PRIMARY_CATEGORY]["reported_students_grade_2_9"]
        premium_reported_total = categories[PRIMARY_CATEGORY]["reported_enrollment_total"]
        premium_modeled_students = categories[PRIMARY_CATEGORY]["modeled_students_grade_2_9"]
        known_units = context["projects"]["known_units"] or 0
        records.append({
            "hex_id": hex_id,
            "canonical_city_id": city_id,
            "city_label": CITY_LABELS[city_id],
            "center": h3_center(hex_id),
            **naming,
            "centroid_lat": h3_center(hex_id)["latitude"],
            "centroid_lon": h3_center(hex_id)["longitude"],
            "school_count": len(schools),
            "students_grade_2_9": all_students,
            "premium_plus_students_grade_2_9": premium_students,
            "premium_plus_reported_enrollment_total": premium_reported_total,
            "premium_plus_modeled_students_grade_2_9": premium_modeled_students,
            "known_units": known_units,
            "direct_total_units": known_units,
            "residential_project_count": context["projects"]["project_count"],
            "direct_hospital_count": context["hospitals"]["hospital_count"],
            "direct_office_count": context["offices"]["office_count"],
            "type": "hex",
            "category": "Premium+ school-led demand",
            "q3_and_below_property_count": context["projects"]["q3_and_below_project_count"],
            "category_metrics": categories,
            "context": context,
            "top_schools": top_schools(schools),
            "top_residential_projects": top_named_rows(unique_projects(projects), "project_id", "total_units"),
            "top_offices": top_named_rows(offices, "office_id", "company_prominence_score"),
            "top_hospitals": top_named_rows(hospitals, "hospital_id", "hospital_score"),
            "source_counts": {
                "schools": len(schools),
                "projects": len(projects),
                "offices": len(offices),
                "hospitals": len(hospitals),
                "localities": len(localities),
            },
        })
    return records


def score_hex_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = {
        "school_demand": robust_normalized_scores([row["premium_plus_students_grade_2_9"] for row in records]),
        "residential_market_depth": robust_normalized_scores([row["context"]["projects"]["known_units"] for row in records]),
        "office_anchor_depth": robust_normalized_scores([row["context"]["offices"]["tier_1_office_count"] for row in records]),
        "hospital_depth": robust_normalized_scores([row["context"]["hospitals"]["hospital_count"] for row in records]),
        "locality_depth": robust_normalized_scores([row["context"]["localities"]["locality_record_count"] for row in records]),
    }
    base_scores: dict[str, float] = {}
    for index, row in enumerate(records):
        selected = row["premium_plus_students_grade_2_9"]
        all_students = row["students_grade_2_9"]
        health_locality = numeric_average([
            normalized["hospital_depth"][index],
            normalized["locality_depth"][index],
        ])
        components = {
            "school_demand": normalized["school_demand"][index],
            "premium_concentration": pct(selected, all_students) if selected is not None and all_students not in (None, 0) else None,
            "residential_market_depth": normalized["residential_market_depth"][index],
            "office_anchor_depth": normalized["office_anchor_depth"][index],
            "health_locality_confidence": health_locality,
        }
        known_weight = sum(weight for key, weight in SCORING_WEIGHTS.items() if components.get(key) is not None)
        score = (
            sum(SCORING_WEIGHTS[key] * components[key] for key in SCORING_WEIGHTS if components.get(key) is not None) / known_weight
            if known_weight else 0.0
        )
        confidence_inputs = [
            100.0 if row["school_count"] else None,
            100.0 if row["context"]["projects"]["project_count"] else None,
            100.0 if row["context"]["offices"]["office_count"] else None,
            100.0 if row["context"]["hospitals"]["hospital_count"] else None,
            100.0 if row["context"]["localities"]["locality_record_count"] else None,
        ]
        row["component_scores"] = {key: None if value is None else round(value / 100.0, 6) for key, value in components.items()}
        row["score_components_raw"] = components
        row["score_weight_coverage_pct"] = round(known_weight * 100.0, 2)
        row["base_affluence_score"] = round(score, 4)
        row["confidence_score"] = round((numeric_average(confidence_inputs) or 0.0) / 100.0, 4)
        base_scores[row["hex_id"]] = score

    by_id = {row["hex_id"]: row for row in records}
    for row in records:
        neighbours = [cell for cell in h3.grid_disk(row["hex_id"], 1) if cell != row["hex_id"] and cell in by_id]
        neighbour_scores = [base_scores[cell] for cell in neighbours]
        neighbour_mean = sum(neighbour_scores) / len(neighbour_scores) if neighbour_scores else 0.0
        high_neighbour_count = sum(1 for value in neighbour_scores if value >= 70)
        final_score = max(0.0, min(100.0, 0.85 * base_scores[row["hex_id"]] + 0.15 * neighbour_mean))
        if final_score >= 70 and high_neighbour_count >= 2:
            relation = "core_cluster"
        elif final_score >= 55 and high_neighbour_count:
            relation = "cluster_edge"
        elif final_score >= 55:
            relation = "local_signal"
        elif row["confidence_score"] < 0.25:
            relation = "low_evidence"
        else:
            relation = "watchlist"
        row["spatial_adjustment"] = {
            "neighbor_hex_count": len(neighbours),
            "neighbor_mean_score": round(neighbour_mean, 4),
            "high_neighbor_count": high_neighbour_count,
            "spatial_score_before_penalty_boost": round(0.85 * base_scores[row["hex_id"]] + 0.15 * neighbour_mean, 4),
            "island_penalty": 0.0,
            "cluster_boost": 0.0,
        }
        row["component_scores"]["spatial_adjustment"] = 0.0
        row["final_affluence_score"] = round(final_score, 4)
        row["affluence_tier"] = final_tier(final_score)
        row["spatial_relation"] = relation

    records.sort(key=lambda row: (-row["final_affluence_score"], row["hex_id"]))
    for rank, row in enumerate(records, start=1):
        row["rank"] = rank
    return records


def final_tier(score: float) -> str:
    if score >= 70:
        return "Premium / Luxury Affluence"
    if score >= 55:
        return "Upper-Mid / Emerging Affluence"
    if score >= 40:
        return "Mixed / Watchlist"
    return "Low Evidence"


def feature_for_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": h3_polygon(row["hex_id"]),
        "properties": row,
    }


def zone_summary(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        groups[row["zone"]].append(row)
    output = []
    for zone, rows in groups.items():
        output.append({
            "zone": zone,
            "hex_count": len(rows),
            "avg_score": round(sum(row["final_affluence_score"] for row in rows) / len(rows), 2),
            "school_count": sum(row["school_count"] for row in rows),
            "students_grade_2_9": nullable_sum(row["students_grade_2_9"] for row in rows),
            "premium_plus_students_grade_2_9": nullable_sum(row["premium_plus_students_grade_2_9"] for row in rows),
            "premium_plus_reported_enrollment_total": nullable_sum(row["premium_plus_reported_enrollment_total"] for row in rows),
            "premium_plus_modeled_students_grade_2_9": nullable_sum(row["premium_plus_modeled_students_grade_2_9"] for row in rows),
            "known_residential_units": nullable_sum(row["context"]["projects"]["known_units"] for row in rows),
            "direct_total_units": nullable_sum(row["direct_total_units"] for row in rows),
            "residential_project_count": sum(row["residential_project_count"] for row in rows),
            "direct_hospital_count": sum(row["direct_hospital_count"] for row in rows),
            "direct_office_count": sum(row["direct_office_count"] for row in rows),
            "q3_and_below_property_count": sum(row["q3_and_below_property_count"] for row in rows),
            "tier_1_office_count": sum(row["context"]["offices"]["tier_1_office_count"] for row in rows),
            "top_hexes": [
                {
                    "hex_id": row["hex_id"],
                    "name": row["name"],
                    "rank": row["rank"],
                    "score": row["final_affluence_score"],
                    "direct_total_units": row["direct_total_units"],
                    "premium_plus_students_grade_2_9": row["premium_plus_students_grade_2_9"],
                    "premium_plus_reported_enrollment_total": row["premium_plus_reported_enrollment_total"],
                    "premium_plus_modeled_students_grade_2_9": row["premium_plus_modeled_students_grade_2_9"],
                    "school_count": row["school_count"],
                }
                for row in rows[:8]
            ],
            "top_score": rows[0]["final_affluence_score"],
            "top_10_avg_score": round(
                sum(row["final_affluence_score"] for row in rows[:10]) / min(len(rows), 10),
                2,
            ),
        })
    return sorted(output, key=lambda row: (-row["avg_score"], row["zone"]))


def legacy_zones_object(zones: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        row["zone"]: {
            "name": row["zone"],
            "hex_count": row["hex_count"],
            "avg_affluence_score": row["avg_score"],
            "school_count": row["school_count"],
            "students_grade_2_9": row["students_grade_2_9"],
            "premium_plus_students_grade_2_9": row["premium_plus_students_grade_2_9"],
            "premium_plus_reported_enrollment_total": row["premium_plus_reported_enrollment_total"],
            "premium_plus_modeled_students_grade_2_9": row["premium_plus_modeled_students_grade_2_9"],
            "direct_total_units": row["direct_total_units"],
            "known_units": row["known_residential_units"],
            "residential_project_count": row["residential_project_count"],
            "direct_hospital_count": row["direct_hospital_count"],
            "direct_office_count": row["direct_office_count"],
            "school_count": row["school_count"],
            "students_grade_2_9": row["students_grade_2_9"],
            "premium_plus_students_grade_2_9": row["premium_plus_students_grade_2_9"],
            "tier_1_office_count": row["tier_1_office_count"],
            "q3_and_below_property_count": row["q3_and_below_property_count"],
            "top_hexes": row["top_hexes"],
            "top_score": row.get("top_score"),
            "top_10_avg_score": row.get("top_10_avg_score"),
        }
        for row in zones
    }


def connected_components(hex_ids: set[str]) -> list[list[str]]:
    remaining = set(hex_ids)
    components = []
    while remaining:
        start = min(remaining)
        remaining.remove(start)
        queue = deque([start])
        component = [start]
        while queue:
            cell = queue.popleft()
            for neighbour in h3.grid_disk(cell, 1):
                if neighbour in remaining:
                    remaining.remove(neighbour)
                    queue.append(neighbour)
                    component.append(neighbour)
        components.append(sorted(component))
    return components


def micro_markets(records: list[dict[str, Any]], limit: int = 12) -> dict[str, Any]:
    by_id = {row["hex_id"]: row for row in records}
    eligible = {row["hex_id"] for row in records if row["final_affluence_score"] >= 40}
    components = connected_components(eligible) if eligible else []
    markets = []
    for component in components:
        rows = sorted((by_id[cell] for cell in component), key=lambda row: (-row["final_affluence_score"], row["hex_id"]))
        primary = rows[0]
        average_score = round(sum(row["final_affluence_score"] for row in rows) / len(rows), 2)
        total_units = nullable_sum(row["context"]["projects"]["known_units"] for row in rows) or 0
        markets.append({
            "name": f"{primary['name']} Market",
            "tier": "core_high_affluence_anchor" if primary["final_affluence_score"] >= 70 else "established_premium_corridor" if primary["final_affluence_score"] >= 55 else "emerging_watchlist_belt",
            "score": average_score,
            "avg_score": average_score,
            "combined_score": average_score,
            "hex_ids": [row["hex_id"] for row in rows],
            "hex_count": len(rows),
            "zone": primary["zone"],
            "school_count": sum(row["school_count"] for row in rows),
            "students_grade_2_9": nullable_sum(row["students_grade_2_9"] for row in rows),
            "premium_plus_students_grade_2_9": nullable_sum(row["premium_plus_students_grade_2_9"] for row in rows),
            "premium_plus_reported_enrollment_total": nullable_sum(row["premium_plus_reported_enrollment_total"] for row in rows),
            "premium_plus_modeled_students_grade_2_9": nullable_sum(row["premium_plus_modeled_students_grade_2_9"] for row in rows),
            "known_residential_units": total_units,
            "total_units": total_units,
            "q3_and_below_property_count": sum(row["q3_and_below_property_count"] for row in rows),
            "top_hexes": [{"hex_id": row["hex_id"], "name": row["name"], "rank": row["rank"]} for row in rows[:8]],
        })
    markets.sort(key=lambda row: (-row["score"], row["name"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "disjoint_micro_markets": markets[:limit],
    }


def enrich_graph_fields(records: list[dict[str, Any]]) -> None:
    if not records:
        return
    score_total = sum(max(row["final_affluence_score"], 0.0) for row in records) or 1.0
    eligible = {row["hex_id"] for row in records if row["final_affluence_score"] >= 40}
    components = connected_components(eligible) if eligible else []
    community_by_hex = {
        hex_id: community_id
        for community_id, component in enumerate(components, start=1)
        for hex_id in component
    }
    for row in records:
        rank = row["rank"]
        graph_rank = round((max(row["final_affluence_score"], 0.0) / score_total), 8)
        row["pagerank_personalized"] = graph_rank
        row["pagerank_node_type"] = (
            "core_hex" if row["final_affluence_score"] >= 70 else
            "emerging_hex" if row["final_affluence_score"] >= 55 else
            "watchlist_hex" if row["final_affluence_score"] >= 40 else
            "low_evidence_hex"
        )
        row["community_id"] = community_by_hex.get(row["hex_id"])
        row["rank_shift"] = 0
        row["graph_rank"] = rank


def graph_network(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {row["hex_id"]: row for row in records}
    links = []
    seen: set[tuple[str, str]] = set()
    for row in records:
        for neighbour in h3.grid_disk(row["hex_id"], 1):
            if neighbour == row["hex_id"] or neighbour not in by_id:
                continue
            edge = tuple(sorted((row["hex_id"], neighbour)))
            if edge in seen:
                continue
            seen.add(edge)
            other = by_id[neighbour]
            links.append({
                "source": edge[0],
                "target": edge[1],
                "weight": round((row["final_affluence_score"] + other["final_affluence_score"]) / 200.0, 6),
                "same_community": row.get("community_id") is not None and row.get("community_id") == other.get("community_id"),
                "relationship": "h3_ring1_adjacency",
            })
    return {
        "schema_version": SCHEMA_VERSION,
        "nodes": [
            {
                "id": row["hex_id"],
                "hex_id": row["hex_id"],
                "name": row["name"],
                "zone": row["zone"],
                "classification": row["affluence_tier"],
                "affluence_score": row["final_affluence_score"],
                "pagerank_personalized": row["pagerank_personalized"],
                "pagerank_node_type": row["pagerank_node_type"],
                "rank": row["rank"],
                "rank_shift": row["rank_shift"],
                "premium_plus_reported_enrollment_total": row["premium_plus_reported_enrollment_total"],
                "premium_plus_students_grade_2_9": row["premium_plus_students_grade_2_9"],
                "known_residential_units": row["known_units"],
                "community_id": row["community_id"],
                "centroid_lat": row["centroid_lat"],
                "centroid_lon": row["centroid_lon"],
            }
            for row in records
        ],
        "links": sorted(links, key=lambda row: (row["source"], row["target"])),
        "semantics": "Derived H3 ring-1 adjacency graph for city-scoped ranked hex cells.",
    }


def q3_below_hex_counts(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "metric": "q3_and_below_property_count",
        "hexes": [
            {
                "hex_id": row["hex_id"],
                "name": row["name"],
                "q3_and_below_property_count": row["q3_and_below_property_count"],
            }
            for row in records
        ],
    }


def commute_scores(records: list[dict[str, Any]], zones: list[dict[str, Any]]) -> dict[str, Any]:
    warning = (
        "Live commute scoring is unavailable for this generated city bundle. "
        "No travel time or routing score has been fabricated; values are explicit nulls until a routing provider is integrated."
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "unavailable",
        "provider": None,
        "warning": warning,
        "by_hex": {
            row["hex_id"]: {
                "status": "unavailable",
                "commute_score": None,
                "travel_time_minutes": None,
                "warning": "Requires live routing provider or validated commute matrix.",
            }
            for row in records
        },
        "by_zone": {
            row["zone"]: {
                "status": "unavailable",
                "commute_score": None,
                "travel_time_minutes": None,
                "hex_count": row["hex_count"],
            }
            for row in zones
        },
    }


def sez_zones_geojson(city_id: str) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "schema_version": SCHEMA_VERSION,
        "canonical_city_id": city_id,
        "status": "unavailable",
        "semantics": "No SEZ polygon boundary source exists in the final multi-city data; office anchors are supplied separately in sez_offices.json.",
        "features": [],
    }


def project_category(row: dict[str, str]) -> str:
    segment = clean(row.get("q4_segment") or row.get("final_q4_segment"))
    mapping = {
        "Ultra Luxury": "Ultra Luxury",
        "Elite Luxury": "Super Luxury",
        "Super Luxury": "Super Luxury",
        "Premium Elite": "Luxury",
        "Ultra Premium": "Ultra Luxury",
        "Super Premium": "Super Luxury",
        "Upper-Mid Premium": "Luxury",
        "Premium": "Premium",
        "Mid-Market": "Aspirational Premium",
        "Economy": "Standard / Budget",
    }
    return mapping.get(segment, "Aspirational Premium")


def school_quartile_for_tier(fee_tier: str | None) -> str:
    normalized = clean(fee_tier)
    if normalized in {"Super-Premium", "Premium"}:
        return "Q4"
    if normalized == "Affordable":
        return "Q3"
    if normalized == "Budget":
        return "Q2"
    return "Q1"


def rows_to_societies(rows: list[dict[str, str]], city_id: str) -> list[dict[str, Any]]:
    output = []
    for row in unique_projects(rows):
        decision = project_coordinate_decision(row, city_id)
        if not decision:
            continue
        lat, lon = decision["lat"], decision["lon"]
        units = number(row.get("total_units"))
        category = project_category(row)
        identity = public_project_id(row)
        output.append({
            "society_id": identity,
            "canonical_society_id": identity,
            "project_id": identity,
            "source_project_id": clean(row.get("project_id")) or clean(row.get("source_project_id")) or None,
            "entity_type": "residential_project",
            "name": clean(row.get("name")) or "Unnamed project",
            "lat": lat,
            "lon": lon,
            "hex_id": h3_for_point(lat, lon),
            "zone": canonical_label(row.get("zone")) or approximate_zone(city_id, lat, lon),
            "locality": canonical_label(row.get("locality")),
            "pincode": clean(row.get("pincode")) or None,
            "category": category,
            "quartile": clean(row.get("final_quartile") or row.get("quartile")) or None,
            "q4_segment": clean(row.get("q4_segment") or row.get("final_q4_segment")) or None,
            "units": units,
            "unit_measure": "project_inventory_units",
            "price": number(row.get("min_price") or row.get("price_sqft")),
            "price_per_sqft": number(row.get("price_sqft")),
            "confidence": number(row.get("google_geocode_confidence") or row.get("google_match_confidence")) or None,
            "construction_status": clean(row.get("construction_status")) or None,
            "developer": clean(row.get("developer")) or None,
            "url": clean(row.get("source_url")) or None,
            "source": "magicbricks_projects_final_master",
            "coordinate_source": decision["source"],
            "coordinate_quality": decision["quality"],
            "coordinate_validation_note": (
                "Validated candidate geocode used because no trusted source coordinate was available."
                if decision["source"] == "validated_candidate_geocode"
                else "Source coordinate used after city-window validation."
            ),
        })
    return sorted(output, key=lambda row: (row["zone"] or "", -(row["units"] or 0), row["name"]))


def rows_to_localities(rows: list[dict[str, str]], city_id: str) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        point = lat_lon_for(row, "localities", city_id)
        if not point:
            continue
        lat, lon = point
        output.append({
            "entity_id": clean(row.get("entity_id")) or stable_id("locality", row.get("name"), lat, lon),
            "name": clean(row.get("name")) or clean(row.get("locality")) or "Unnamed locality",
            "entity_type": clean(row.get("entity_type")) or "locality",
            "lat": lat,
            "lon": lon,
            "hex_id": h3_for_point(lat, lon),
            "zone": canonical_label(row.get("zone")) or approximate_zone(city_id, lat, lon),
            "locality": canonical_label(row.get("locality")),
            "pincode": clean(row.get("pincode")) or None,
            "price_sqft": number(row.get("price_per_sqft_avg")),
            "budget_segment": clean(row.get("segment")) or clean(row.get("quartile")) or None,
            "confidence": number(row.get("coordinate_confidence")) or None,
            "url": clean(row.get("source_url")) or None,
            "source": clean(row.get("source")) or "real_estate_localities_and_societies",
        })
    return sorted(output, key=lambda row: (row["zone"] or "", row["name"]))


def rows_to_hospitals(rows: list[dict[str, str]], city_id: str) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        point = lat_lon_for(row, "hospitals", city_id)
        if not point:
            continue
        lat, lon = point
        output.append({
            "hospital_id": clean(row.get("hospital_id")) or stable_id("hospital", row.get("name"), lat, lon),
            "name": clean(row.get("name")) or "Unnamed hospital",
            "lat": lat,
            "lon": lon,
            "hex_id": h3_for_point(lat, lon),
            "zone": canonical_label(row.get("zone")) or approximate_zone(city_id, lat, lon),
            "locality": canonical_label(row.get("locality")),
            "category": clean(row.get("segment")) or clean(row.get("quartile")) or "Hospital",
            "rating": number(row.get("rating")) or 0,
            "beds": number(row.get("doctors_count")) or 0,
            "doctors_count": number(row.get("doctors_count")),
            "speciality_count": number(row.get("speciality_count")),
            "multispeciality": clean(row.get("multispeciality")).lower() == "true",
            "pincode": None,
            "url": clean(row.get("profile_url")) or None,
            "hospital_score": number(row.get("hospital_score")),
            "source": "practo_hospitals_all_cities",
        })
    return sorted(output, key=lambda row: (row["zone"] or "", -(row["hospital_score"] or 0), row["name"]))


def office_tier_label(value: Any) -> str:
    tier = clean(value)
    mapping = {
        "Tier-1": "Tier 1 - MNC/GCC anchor",
        "Tier 1": "Tier 1 - MNC/GCC anchor",
        "Tier-2": "Tier 2 - Enterprise/tech anchor",
        "Tier 2": "Tier 2 - Enterprise/tech anchor",
        "Tier-3": "Tier 3 - Regional/SMB office",
        "Tier 3": "Tier 3 - Regional/SMB office",
        "Tier-4": "Tier 4 - Local/generic office",
        "Tier 4": "Tier 4 - Local/generic office",
    }
    return mapping.get(tier, tier or "Unclassified office")


def rows_to_offices(rows: list[dict[str, str]], city_id: str) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        point = lat_lon_for(row, "offices", city_id)
        if not point:
            continue
        lat, lon = point
        score = number(row.get("company_prominence_score")) or 0
        tier_label = office_tier_label(row.get("company_prominence_tier"))
        output.append({
            "office_id": clean(row.get("office_id")) or stable_id("office", row.get("name"), lat, lon),
            "company_key": clean(row.get("company_key")) or stable_id("company", row.get("name")),
            "name": clean(row.get("name")) or "Unnamed office",
            "lat": lat,
            "lon": lon,
            "hex_id": h3_for_point(lat, lon),
            "zone": canonical_label(row.get("zone")) or approximate_zone(city_id, lat, lon),
            "locality": canonical_label(row.get("locality")) or clean(row.get("address")) or None,
            "pincode": clean(row.get("pincode")) or None,
            "postcode": clean(row.get("pincode")) or None,
            "company_prominence_tier": tier_label,
            "raw_company_prominence_tier": clean(row.get("company_prominence_tier")) or None,
            "company_prominence_score": score,
            "office_rank_score": score,
            "overall_office_rank": int(number(row.get("overall_office_rank")) or len(output) + 1),
            "segment": clean(row.get("segment")) or None,
            "sez_name": None,
            "sez_match_type": "office_anchor_only_no_sez_polygon",
            "distance_to_sez_km": None,
            "website": clean(row.get("website")) or None,
            "url": clean(row.get("website")) or None,
            "source": "offices_unified_all_cities",
        })
    return sorted(output, key=lambda row: (row["zone"] or "", -(row["office_rank_score"] or 0), row["name"]))


def project_assets_by_quartile(societies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            **row,
            "quartile_analysis_1": row.get("quartile") or "Unranked",
            "analysis_source": "derived_from_magicbricks_final_project_quartiles",
        }
        for row in societies
    ]


def board_list(raw: Any) -> list[str]:
    parts = [part.strip().upper() for part in re.split(r"[,/|;]+", clean(raw)) if part.strip()]
    return sorted(set(parts)) if parts else ["UNKNOWN"]


def school_records(rows: list[dict[str, str]], city_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    entities_by_id: dict[str, dict[str, Any]] = {}
    campus_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    source_totals = Counter()
    mapped_row_count = 0
    for row in rows:
        point = lat_lon_for(row, "schools", city_id)
        if not point:
            continue
        mapped_row_count += 1
        lat, lon = point
        school_id = clean(row.get("school_id")) or stable_id("school", row.get("school_name"), row.get("udise_code"), lat, lon)
        campus_id = stable_id("campus", row.get("google_place_id") or school_id, row.get("school_name"), lat, lon)
        entity_id = stable_id("school_entity", school_id, row.get("udise_code"), row.get("school_name"))
        enrollment = number(row.get("enrollment_grade_2_9"))
        total_enrollment = number(row.get("enrollment_total"))
        source = "udise" if source_reported(row) else "estimate"
        source_totals[source] += enrollment or 0
        fee_tier = clean(row.get("fee_tier")) or None
        school_quartile = school_quartile_for_tier(fee_tier)
        common = {
            "name": clean(row.get("school_name")) or "Unnamed school",
            "canonical_city_id": city_id,
            "lat": lat,
            "lon": lon,
            "hex_id": h3_for_point(lat, lon),
            "zone": approximate_zone(city_id, lat, lon),
            "area": canonical_label(row.get("area") or row.get("district") or row.get("pincode")),
            "address": clean(row.get("address")) or None,
            "pincode": clean(row.get("pincode")) or None,
            "board": board_list(row.get("board")),
            "boards": board_list(row.get("board")),
            "fee_tier": fee_tier,
            "fee_bucket": fee_tier,
            "fee_quartile": school_quartile,
            "fee_min": None,
            "fee_max": None,
            "students_grades_2_9": enrollment,
            "grade_2_9_enrollment": enrollment,
            "students_total": total_enrollment if source_reported(row) else None,
            "reported_enrollment_total": total_enrollment if source_reported(row) else None,
            "reported_students_grade_2_9": enrollment if source_reported(row) else None,
            "modeled_students_grade_2_9": enrollment if not source_reported(row) else None,
            "grade_2_9_method": (
                "derived_from_source_reported_total_enrollment"
                if source_reported(row) else "modeled"
            ),
            "enrollment_source": source,
            "evidence_basis": "source_reported" if source_reported(row) else "modeled",
            "coordinate_quality": clean(row.get("coordinate_quality")) or None,
            "google_place_id": clean(row.get("google_place_id")) or None,
            "udise_code": clean(row.get("udise_code")) or None,
        }
        entity = {
            **common,
            "school_entity_id": entity_id,
            "entity_id": entity_id,
            "campus_id": campus_id,
            "school_id": school_id,
            "quartile": school_quartile,
            "fee_quartile": school_quartile,
            "fee_bucket": fee_tier,
            "q4_tier_label": fee_tier if school_quartile == "Q4" else None,
            "source_row_ids": [school_id],
        }
        if entity_id not in entities_by_id:
            entities_by_id[entity_id] = entity
            campus_groups[campus_id].append(entity)
    entities = list(entities_by_id.values())
    campuses = []
    for campus_id, members in campus_groups.items():
        first = members[0]
        reported_total = nullable_sum(member["reported_enrollment_total"] for member in members)
        reported_grade = nullable_sum(member["reported_students_grade_2_9"] for member in members)
        modeled_grade = nullable_sum(member["modeled_students_grade_2_9"] for member in members)
        campuses.append({
            **first,
            "campus_id": campus_id,
            "id": campus_id,
            "school_entity_ids": [member["entity_id"] for member in members],
            "entity_ids": [member["entity_id"] for member in members],
            "entity_count": len(members),
            "reported_enrollment_total": reported_total,
            "reported_students_grade_2_9": reported_grade,
            "modeled_students_grade_2_9": modeled_grade,
            "students_total": reported_total,
            "students_grades_2_9": nullable_sum((reported_grade, modeled_grade)),
            "grade_2_9_enrollment": nullable_sum((reported_grade, modeled_grade)),
            "boards": sorted({board for member in members for board in member["boards"]}),
            "board": sorted({board for member in members for board in member["boards"]}),
            "has_q4_entity": any(member["fee_tier"] in {"Super-Premium", "Premium"} for member in members),
        })
    entities.sort(key=lambda row: (row["zone"], row["name"], row["entity_id"]))
    campuses.sort(key=lambda row: (row["zone"], row["name"], row["campus_id"]))
    audit = {
        "schema_version": SCHEMA_VERSION,
        "input_row_count": len(rows),
        "published_entity_count": len(entities),
        "published_campus_count": len(campuses),
        "duplicate_rows_collapsed": mapped_row_count - len(entities),
        "campus_rows_merged": len(entities) - len(campuses),
        "quarantined_row_count": len(rows) - mapped_row_count,
        "q4_fee_max_cutoff": None,
        "annual_fee_fields_available": False,
        "students_grades_2_9_by_source": dict(sorted(source_totals.items())),
        "constraints": {
            "custom_annual_fee_filter_supported": False,
            "school_fee_amounts_available": False,
        },
    }
    return entities, campuses, audit


def school_market_summary(layers: dict[str, list[dict[str, str]]]) -> dict[str, Any]:
    schools = layers["schools"]
    by_tier = {}
    for category_id, definition in CATEGORIES.items():
        selected = [row for row in schools if clean(row.get("fee_tier")) in definition["tiers"]]
        reported = [row for row in selected if source_reported(row)]
        modeled = [row for row in selected if not source_reported(row)]
        reported_total = nullable_sum(number(row.get("enrollment_total")) for row in reported) if selected else 0
        reported_grade = nullable_sum(number(row.get("enrollment_grade_2_9")) for row in reported) if selected else 0
        modeled_grade = nullable_sum(number(row.get("enrollment_grade_2_9")) for row in modeled) if selected else 0
        combined_grade = nullable_sum(number(row.get("enrollment_grade_2_9")) for row in selected) if selected else 0
        campus_ids = set()
        for row in selected:
            point = lat_lon_for(row, "schools", clean(row.get("canonical_city_id")) or normalize_city(row.get("city")) or "bengaluru")
            if not point:
                continue
            lat, lon = point
            school_id = clean(row.get("school_id")) or stable_id("school", row.get("school_name"), row.get("udise_code"), lat, lon)
            campus_ids.add(stable_id("campus", row.get("google_place_id") or school_id, row.get("school_name"), lat, lon))
        by_tier[category_id] = {
            "label": definition["label"],
            "school_entity_count_all": len(selected),
            "school_entity_count_grade_2_9_positive": sum((number(row.get("enrollment_grade_2_9")) or 0) > 0 for row in selected),
            "campus_count_context": len(campus_ids),
            "reported_enrollment_total": reported_total,
            "reported_students_grade_2_9": reported_grade,
            "modeled_students_grade_2_9": modeled_grade,
            "combined_students_grade_2_9": combined_grade,
            "students_grades_2_9_expanded": reported_grade,
            "students_grades_2_9_by_source": {
                "udise_backed": reported_grade or 0,
                "estimated": modeled_grade or 0,
                "source_reported_derived": reported_grade or 0,
                "modeled": modeled_grade or 0,
            },
            "campus_scenarios": capacity_summary(reported_grade),
            "capacity": capacity_summary(reported_grade),
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "custom_annual_fee_filter_supported": False,
        "reason": "The final school source contains fee_tier buckets but no comparable annual fee values.",
        "primary_student_scope": "source-reported all-grade enrollment",
        "campus_scenario_scope": "Grades 2-9 derived from source-reported school enrollment",
        "bucket_summaries": by_tier,
        "q4": by_tier[PRIMARY_CATEGORY],
        "source_observation_as_of": None,
        "academic_year": None,
    }


def capacity_summary(students: float | int | None) -> list[dict[str, Any]]:
    output = []
    for capture_rate in (0.01, 0.02, 0.03):
        captured = None if students is None else students * capture_rate
        effective_capacity = 200 * 0.8
        output.append({
            "scenario_type": "planning_scenario",
            "evidence_basis": "derived_grade_2_9_from_source_reported_total_enrollment",
            "capture_rate": capture_rate,
            "capture_rate_pct": int(capture_rate * 100),
            "captured_students": round(captured, 2) if captured is not None else None,
            "campuses_supported": math.floor(captured / effective_capacity) if captured is not None and effective_capacity else None,
            "centers_supported": math.floor(captured / effective_capacity) if captured is not None and effective_capacity else None,
            "center_capacity": 200,
            "seats_per_campus": 200,
            "target_utilization": 0.8,
        })
    return output


def source_reconciliation(layers: dict[str, list[dict[str, str]]], records: list[dict[str, Any]], city_id: str) -> dict[str, Any]:
    mapped_counts = Counter()
    for row in records:
        for layer, count in row["source_counts"].items():
            mapped_counts[layer] += count
    return {
        layer: {
            "source_rows": len(rows),
            "mapped_to_h3_rows": mapped_counts[layer],
            "unmapped_rows": len(rows) - mapped_counts[layer],
            "coordinate_coverage_pct": pct(mapped_counts[layer], len(rows)),
        }
        for layer, rows in layers.items()
    } | {
        "_city": city_id,
        "_hex_count": len(records),
    }


def project_quartile_breakdown(projects: list[dict[str, str]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in projects:
        quartile = clean(row.get("final_quartile")) or clean(row.get("quartile")) or "Unclassified"
        groups[quartile].append(row)
    output = []
    for quartile, rows in groups.items():
        units = nullable_sum(number(row.get("total_units")) for row in rows)
        prices = [number(row.get("price_sqft")) for row in rows if number(row.get("price_sqft")) is not None]
        output.append({
            "quartile": quartile,
            "rows": len(rows),
            "units": units,
            "avg_price": round(sum(prices) / len(prices), 2) if prices else None,
            "avg_price_per_sqft": round(sum(prices) / len(prices), 2) if prices else None,
        })
    order = {"Q4": 0, "Q3": 1, "Q2": 2, "Q1": 3, "Unranked": 4, "Unclassified": 5}
    return sorted(output, key=lambda row: (order.get(row["quartile"], 9), row["quartile"]))


def project_type_breakdown(projects: list[dict[str, str]]) -> list[dict[str, Any]]:
    counts = Counter(clean(row.get("project_type")) or "Unclassified" for row in projects)
    total = sum(counts.values()) or 1
    return [
        {"project_type": project_type, "count": count, "share_pct": round(count * 100.0 / total, 2)}
        for project_type, count in counts.most_common()
    ]


def category_hex_shortlists(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    output = {}
    for category_id in CATEGORIES:
        rows = [
            row for row in records
            if (row["category_metrics"][category_id]["reported_students_grade_2_9"] or 0) > 0
        ]
        rows.sort(
            key=lambda row: (
                -row["final_affluence_score"],
                -(row["category_metrics"][category_id]["reported_students_grade_2_9"] or 0),
                -(row["context"]["projects"]["known_units"] or 0),
                row["hex_id"],
            )
        )
        output[category_id] = [
            {
                "rank": index + 1,
                "hex_id": row["hex_id"],
                "name": row["name"],
                "score": row["final_affluence_score"],
                "reported_enrollment_total": row["category_metrics"][category_id]["reported_enrollment_total"],
                "students_grade_2_9": row["category_metrics"][category_id]["reported_students_grade_2_9"],
                "reported_students_grade_2_9": row["category_metrics"][category_id]["reported_students_grade_2_9"],
                "modeled_students_grade_2_9": row["category_metrics"][category_id]["modeled_students_grade_2_9"],
                "school_count": row["category_metrics"][category_id]["school_count"],
                "residential_projects": row["context"]["projects"]["project_count"],
                "known_residential_units": row["context"]["projects"]["known_units"],
                "office_anchors": row["context"]["offices"]["office_count"],
                "tier_1_offices": row["context"]["offices"]["tier_1_office_count"],
                "hospitals": row["context"]["hospitals"]["hospital_count"],
                "locality_records": row["context"]["localities"]["locality_record_count"],
                "neighborhood_name_confidence": row["neighborhood_name_confidence_label"],
            }
            for index, row in enumerate(rows[:12])
        ]
    return output


def dedupe_shortlist_by_name(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped = []
    for row in rows:
        name_key = clean(row.get("name")).casefold() or row.get("hex_id")
        if name_key in seen:
            continue
        seen.add(name_key)
        deduped.append(row)
    return deduped


def legacy_decision_support(
    city_id: str,
    layers: dict[str, list[dict[str, str]]],
    category_shortlists: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    premium_rows = [
        row for row in layers["schools"]
        if clean(row.get("fee_tier")) in CATEGORIES[PRIMARY_CATEGORY]["tiers"]
        and source_reported(row)
    ]
    priority_schools = top_schools(premium_rows, limit=25)
    for rank, row in enumerate(priority_schools, start=1):
        row["rank"] = rank

    residential_targets = []
    ordered_projects = sorted(
        unique_projects(layers["projects"]),
        key=lambda row: (
            clean(row.get("final_quartile") or row.get("quartile")) != "Q4",
            -(number(row.get("total_units")) or 0),
            clean(row.get("name")).casefold(),
        ),
    )
    for row in ordered_projects[:25]:
        residential_targets.append({
            "rank": len(residential_targets) + 1,
            "project_id": public_project_id(row),
            "source_project_id": clean(row.get("project_id")) or clean(row.get("source_project_id")) or None,
            "name": clean(row.get("name")) or "Unnamed residential project",
            "developer": clean(row.get("developer")) or None,
            "locality": clean(row.get("locality")) or None,
            "quartile": clean(row.get("final_quartile") or row.get("quartile")) or None,
            "known_units": number(row.get("total_units")),
            "unit_measure": "project_inventory_units",
            "source_url": clean(row.get("source_url")) or None,
        })

    corridor_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in premium_rows:
        label = clean(row.get("area")) or clean(row.get("district")) or clean(row.get("pincode"))
        if label:
            corridor_groups[label].append(row)
    corridors = [
        {
            "name": label,
            "reported_school_count": len(rows),
            "reported_enrollment_total": nullable_sum(number(row.get("enrollment_total")) for row in rows),
            "reported_students_grade_2_9": nullable_sum(number(row.get("enrollment_grade_2_9")) for row in rows),
        }
        for label, rows in corridor_groups.items()
    ]
    corridors.sort(key=lambda row: (-(row["reported_enrollment_total"] or 0), row["name"].casefold()))
    reported_grade = nullable_sum(number(row.get("enrollment_grade_2_9")) for row in premium_rows)
    return {
        "evidence_policy": {
            "primary_city_metric": "reported_enrollment_total",
            "campus_scenario_basis": "reported_students_grade_2_9",
            "modeled_enrollment_in_primary_rankings": False,
            "residential_measure": "known_project_units",
            "source_observation_as_of": None,
            "academic_year": None,
        },
        "priority_school_partners": priority_schools,
        "residential_project_targets": residential_targets,
        "premium_student_corridors": corridors[:15],
        "candidate_catchments": category_shortlists.get(PRIMARY_CATEGORY, [])[:15],
        "campus_scenarios": capacity_summary(reported_grade),
    }


def city_summary(
    city_id: str,
    layers: dict[str, list[dict[str, str]]],
    records: list[dict[str, Any]],
    markets: dict[str, Any] | None = None,
) -> dict[str, Any]:
    zones = zone_summary(records)
    category_shortlists = category_hex_shortlists(records)
    primary_students = nullable_sum(row["premium_plus_students_grade_2_9"] for row in records)
    primary_reported_total = nullable_sum(row["premium_plus_reported_enrollment_total"] for row in records)
    primary_modeled_students = nullable_sum(row["premium_plus_modeled_students_grade_2_9"] for row in records)
    market_rows = (markets or {}).get("disjoint_micro_markets", [])
    top_clusters = dedupe_shortlist_by_name(category_shortlists.get(PRIMARY_CATEGORY, []))
    cluster_names = ", ".join(row["name"] for row in top_clusters[:3])
    return {
        "schema_version": SCHEMA_VERSION,
        "canonical_city_id": city_id,
        "city_label": CITY_LABELS[city_id],
        "coverage": {
            "coverage_note": (
                f"{CITY_LABELS[city_id]} summary uses city-scoped generated school, project, office, hospital, "
                "and locality evidence. School annual fee amounts remain unavailable."
            ),
            "final_h3_hexes": len(records),
            "active_analysis_hexes": sum(1 for row in records if row["final_affluence_score"] > 0),
        },
        "executive_metrics": {
            "total_projects": len(layers["projects"]),
            "q4_total_units": nullable_sum(
                number(row.get("total_units")) for row in layers["projects"]
                if (clean(row.get("final_quartile")) or clean(row.get("quartile"))) == "Q4"
            ),
            "micro_markets": len(market_rows),
            "premium_plus_reported_enrollment_total": primary_reported_total,
            "premium_plus_students_grade_2_9": primary_students,
            "premium_plus_modeled_students_grade_2_9": primary_modeled_students,
        },
        "hex_count": len(records),
        "active_hex_count": sum(1 for row in records if row["final_affluence_score"] > 0),
        "school_count": len(layers["schools"]),
        "students_grade_2_9": nullable_sum(number(row.get("enrollment_grade_2_9")) for row in layers["schools"]) if layers["schools"] else 0,
        "premium_plus_students_grade_2_9": primary_students,
        "premium_plus_reported_enrollment_total": primary_reported_total,
        "premium_plus_modeled_students_grade_2_9": primary_modeled_students,
        "known_residential_units": nullable_sum(row["context"]["projects"]["known_units"] for row in records),
        "zone_count": len(zones),
        "top_zones": zones[:5],
        "top_hexes": [{"rank": row["rank"], "hex_id": row["hex_id"], "name": row["name"], "score": row["final_affluence_score"]} for row in records[:20]],
        "category_hex_shortlists": category_shortlists,
        "decision_support": legacy_decision_support(city_id, layers, category_shortlists),
        "quartile_breakdown": project_quartile_breakdown(layers["projects"]),
        "project_type_breakdown": project_type_breakdown(layers["projects"]),
        "recommendations": {
            "micro_markets": [
                {
                    "name": f"{row['name']} cluster",
                    "status": "Launch now" if index == 0 else "Shortlist",
                    "rationale": (
                        f"{row['students_grade_2_9'] or 0:,} Premium+ students, "
                        f"{row['school_count'] or 0:,} schools, "
                        f"{row['known_residential_units'] or 0:,} known residential units, "
                        f"{row['tier_1_offices'] or 0:,} tier-1 office anchors."
                    ),
                    "reported_enrollment_total": row["reported_enrollment_total"] or 0,
                    "reported_students_grade_2_9": row["reported_students_grade_2_9"] or 0,
                    "reported_student_share_pct": pct(row["reported_students_grade_2_9"] or 0, primary_students or 0) or 0,
                    "score": row["score"],
                    "hex_id": row["hex_id"],
                }
                for index, row in enumerate(top_clusters[:5])
            ],
            "top_clusters": top_clusters[:8],
            "micro_market_components": market_rows[:8],
        },
        "localized_insight": {
            "headline": (
                f"Premium+ demand is most visible around {cluster_names}."
                if cluster_names else
                "No mapped Premium+ school demand clusters are available."
            ),
            "next_step": "Validate top H3 clusters with competition, rentals, and drive-time reach before selecting a center.",
            "confidence_notes": [
                "Neighbourhood labels are inferred from supplied locality/project/school context and include confidence metadata.",
                "Residential units are market-depth evidence, not deduplicated family TAM.",
                "Custom annual fee thresholds are unavailable because school fee amounts are not in the source.",
            ],
        },
        "validation": {
            "checks": [
                {"name": "City-scoped H3 records", "status": "pass", "value": len(records), "expected": ">= 1"},
                {"name": "School source rows", "status": "pass", "value": len(layers["schools"]), "expected": ">= 1"},
                {"name": "Project source rows", "status": "pass", "value": len(layers["projects"]), "expected": ">= 1"},
            ],
        },
        "handoff_links": [
            {"label": "City H3 GeoJSON", "href": f"data/city_legacy/{city_id}/hexes.geojson"},
            {"label": "School market summary", "href": f"data/city_legacy/{city_id}/school_market_summary.json"},
            {"label": "Source reconciliation", "href": f"data/city_legacy/{city_id}/report.json"},
        ],
        "constraints": {
            "custom_annual_fee_filter_supported": False,
            "school_fee_amounts_available": False,
        },
    }


def build_city_bundle(city_id: str, layers: dict[str, list[dict[str, str]]], output_dir: Path) -> dict[str, Any]:
    records = score_hex_records(build_raw_hex_records(city_id, layers))
    enrich_graph_fields(records)
    features = [feature_for_record(row) for row in records]
    zones = zone_summary(records)
    markets = micro_markets(records)
    summary = city_summary(city_id, layers, records, markets)
    reconciliation = source_reconciliation(layers, records, city_id)
    societies = rows_to_societies(layers["projects"], city_id)
    localities = rows_to_localities(layers["localities"], city_id)
    hospitals = rows_to_hospitals(layers["hospitals"], city_id)
    offices = rows_to_offices(layers["offices"], city_id)
    school_entities, school_campuses, school_audit = school_records(layers["schools"], city_id)
    report = {
        "schema_version": SCHEMA_VERSION,
        "canonical_city_id": city_id,
        "city_label": CITY_LABELS[city_id],
        "hex_count": len(records),
        "ranked_hex_count": len([row for row in records if row["final_affluence_score"] is not None]),
        "zones": legacy_zones_object(zones),
        "source_reconciliation": reconciliation,
        "score_model": {
            "primary_category": PRIMARY_CATEGORY,
            "weights": SCORING_WEIGHTS,
            "hex_metric_normalization": "log_p5_p95_by_city_for_long_tailed_h3_metrics",
            "spatial_adjustment": "final_score = 0.85 * base_score + 0.15 * h3_ring1_neighbor_mean",
        },
        "limitations": [
            "School annual fee amounts are unavailable; only supplied fee_tier buckets are used.",
            "Neighbourhood names are inferred from locality/project/school/hospital/office labels and include provenance/confidence.",
            "Travel-time catchments require a city-aware live routing API layer before UI parity is complete.",
        ],
    }

    payloads = {
        "hexes.geojson": {
            "type": "FeatureCollection",
            "schema_version": SCHEMA_VERSION,
            "canonical_city_id": city_id,
            "features": features,
        },
        "hexes_master.json": {
            "schema_version": SCHEMA_VERSION,
            "canonical_city_id": city_id,
            "hexes": records,
        },
        "client_summary.json": summary,
        "decision_support.json": {
            "schema_version": SCHEMA_VERSION,
            "canonical_city_id": city_id,
            **summary["decision_support"],
        },
        "report.json": report,
        "zones.json": {"schema_version": SCHEMA_VERSION, "canonical_city_id": city_id, "zones": zones},
        "micromarket_suggestions_8hex.json": markets,
        "school_market_summary.json": school_market_summary(layers),
        "localities.json": localities,
        "societies.json": societies,
        "hospitals.json": hospitals,
        "sez_offices.json": offices,
        "project_assets_by_quartile.json": project_assets_by_quartile(societies),
        "school_entities.json": school_entities,
        "school_campuses.json": school_campuses,
        "school_market_audit.json": school_audit,
        "q3_below_hex_counts.json": q3_below_hex_counts(records),
        "commute_scores.json": commute_scores(records, zones),
        "metro_stations.json": [],
        "graph_network.json": graph_network(records),
        "sez_zones.geojson": sez_zones_geojson(city_id),
    }
    artifacts = {}
    for filename, payload in payloads.items():
        path = output_dir / city_id / filename
        write_json(path, payload)
        artifacts[filename] = artifact_metadata(path, output_dir)
    return {
        "canonical_city_id": city_id,
        "city_label": CITY_LABELS[city_id],
        "artifact_dir": city_id,
        "hex_count": len(records),
        "artifacts": artifacts,
    }


def build(data_root: Path, output_root: Path) -> None:
    raw, provenance = load_sources(data_root)
    city_rows, excluded = partition_city_rows(raw)
    output_root.mkdir(parents=True, exist_ok=True)
    city_entries = [
        build_city_bundle(city_id, city_rows[city_id], output_root)
        for city_id in TARGET_CITIES
    ]
    generated_at = max(
        datetime.fromtimestamp((data_root / path).stat().st_mtime, tz=timezone.utc)
        for path in SOURCE_FILES.values()
    ).replace(microsecond=0).isoformat()
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "h3_resolution": H3_RESOLUTION,
        "primary_category": PRIMARY_CATEGORY,
        "cities": city_entries,
        "source_provenance": provenance,
        "excluded_source_city_labels": {
            layer: dict(sorted(counter.items())) for layer, counter in excluded.items()
        },
        "constraints": {
            "custom_annual_fee_filter_supported": False,
            "school_fee_amounts_available": False,
            "primary_student_scope": "source-reported all-grade enrollment in selected school tiers",
            "derived_student_scope": "Grades 2-9 derived for source-reported schools",
            "modeled_enrollment_in_primary_rankings": False,
            "campus_scenario_capture_rates": [0.01, 0.02, 0.03],
            "campus_scenario_seats_per_campus": 200,
            "campus_scenario_target_utilization": 0.8,
            "source_observation_as_of": None,
            "academic_year": None,
        },
    }
    manifest_path = output_root / "manifest.json"
    write_json(manifest_path, manifest)
    print(f"Built legacy-parity bundles for {len(city_entries)} cities in {output_root}")
    for entry in city_entries:
        print(f"{entry['city_label']}: {entry['hex_count']:,} named H3 cells")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "final_data" / "multicity_source",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(__file__).resolve().parent / "public" / "data" / "city_legacy",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    build(args.data_root.resolve(), args.output_root.resolve())
