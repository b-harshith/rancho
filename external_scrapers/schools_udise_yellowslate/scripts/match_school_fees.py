#!/usr/bin/env python3
"""Match fee-summary schools to operational UDISE schools and generate coverage outputs."""

from __future__ import annotations

import argparse
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


NA = {"", "na", "n/a", "nan", "none", "null", "unknown"}
REPLACEMENTS = {
    "sch": "school", "hs": "high school", "hps": "higher primary school",
    "lps": "lower primary school", "ps": "public school", "intl": "international",
    "jnr": "junior", "collage": "college", "acadamy": "academy",
}


def text(value: Any) -> str | None:
    value = str(value or "").strip()
    return None if value.lower() in NA else value


def norm_name(value: Any) -> str:
    value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    tokens = [REPLACEMENTS.get(token, token) for token in value.split()]
    return " ".join(tokens)


def name_score(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    sequence = SequenceMatcher(None, left, right).ratio()
    a, b = set(left.split()), set(right.split())
    token = len(a & b) / len(a | b) if a | b else 0.0
    containment = min(len(a & b) / len(a), len(a & b) / len(b)) if a and b else 0.0
    return max(sequence, 0.65 * token + 0.35 * containment)


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def valid_coord(lat: Any, lon: Any) -> bool:
    return (
        isinstance(lat, (int, float)) and isinstance(lon, (int, float))
        and lat != 0 and lon != 0 and -90 <= lat <= 90 and -180 <= lon <= 180
    )


def coord_score(distance: float | None) -> float:
    if distance is None:
        return 0.0
    if distance <= 100: return 1.0
    if distance <= 300: return 0.9
    if distance <= 750: return 0.75
    if distance <= 2_000: return 0.5
    if distance <= 5_000: return 0.2
    return 0.0


def pincode(value: Any) -> str | None:
    match = re.fullmatch(r"\d{6}", str(value or "").strip())
    return match.group() if match else None


def board_tokens(value: Any) -> set[str]:
    value = norm_name(value)
    aliases = {"international board": "ib", "state board": "state"}
    for source, target in aliases.items():
        value = value.replace(source, target)
    return {token for token in re.split(r"\s+", value) if token in {"cbse", "icse", "ib", "igcse", "cambridge", "state"}}


def match(fees: list[dict[str, Any]], schools: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_pin: dict[str, set[int]] = defaultdict(set)
    by_name: dict[str, set[int]] = defaultdict(set)
    grid: dict[tuple[int, int], set[int]] = defaultdict(set)
    prepared = []
    for index, school in enumerate(schools):
        meta, location = school["metadata"], school["metadata"]["location"]
        name = norm_name(meta.get("school_name"))
        pins = {pincode(meta.get("searched_pincode")), pincode(meta.get("reported_pincode"))} - {None}
        lat, lon = location.get("latitude"), location.get("longitude")
        record = {"name": name, "pins": pins, "lat": lat, "lon": lon}
        prepared.append(record)
        for code in pins: by_pin[code].add(index)
        by_name[name].add(index)
        if valid_coord(lat, lon): grid[(round(lat * 100), round(lon * 100))].add(index)

    decisions = []
    used_schools: set[int] = set()
    for fee_index, fee in enumerate(fees):
        fee_name = norm_name(fee.get("School Name"))
        fee_pin = pincode(fee.get("Pincode"))
        lat, lon = fee.get("Latitude"), fee.get("Longitude")
        candidates: set[int] = set()
        if fee_pin: candidates |= by_pin.get(fee_pin, set())
        candidates |= by_name.get(fee_name, set())
        if valid_coord(lat, lon):
            gx, gy = round(lat * 100), round(lon * 100)
            for x in range(gx - 2, gx + 3):
                for y in range(gy - 2, gy + 3): candidates |= grid.get((x, y), set())

        ranked = []
        fee_boards = board_tokens(fee.get("Board"))
        for school_index in candidates:
            school = schools[school_index]
            candidate = prepared[school_index]
            similarity = name_score(fee_name, candidate["name"])
            distance = None
            if valid_coord(lat, lon) and valid_coord(candidate["lat"], candidate["lon"]):
                distance = haversine(lat, lon, candidate["lat"], candidate["lon"])
            pin_match = bool(fee_pin and fee_pin in candidate["pins"])
            affiliation = school["metadata"].get("board_affiliation") or {}
            school_boards = board_tokens(" ".join(str(v or "") for v in affiliation.values()))
            board_match = bool(fee_boards and school_boards and fee_boards & school_boards)
            score = 0.6 * similarity + 0.22 * coord_score(distance) + 0.13 * pin_match + 0.05 * board_match
            acceptable = (
                (pin_match and similarity >= 0.72)
                or (similarity >= 0.9 and (distance is None or distance <= 5_000))
                or (distance is not None and distance <= 250 and similarity >= 0.42)
                or (distance is not None and distance <= 750 and similarity >= 0.65)
            )
            if acceptable:
                ranked.append((score, similarity, distance, pin_match, board_match, school_index))
        ranked.sort(reverse=True, key=lambda item: item[0])
        best = ranked[0] if ranked else None
        runner_up = ranked[1] if len(ranked) > 1 else None
        ambiguous = bool(best and runner_up and best[0] - runner_up[0] < 0.055)
        duplicate = bool(best and best[5] in used_schools)
        if best and not ambiguous and not duplicate:
            used_schools.add(best[5])
            method = "pincode+name" if best[3] else "coordinates+name" if best[2] is not None else "name"
            decisions.append({
                "fee_index": fee_index, "school_index": best[5], "status": "matched",
                "method": method, "confidence": round(best[0], 4),
                "name_similarity": round(best[1], 4),
                "distance_meters": round(best[2], 1) if best[2] is not None else None,
                "pincode_match": best[3], "board_match": best[4],
            })
        else:
            decisions.append({
                "fee_index": fee_index, "school_index": None,
                "status": "ambiguous" if ambiguous or duplicate else "unmatched",
                "reason": "close competing match" if ambiguous else "duplicate school match" if duplicate else "no candidate passed thresholds",
            })
    return decisions, prepared


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schools", type=Path, default=Path("data/output/schools_analysis.json"))
    parser.add_argument("--fees", type=Path, default=Path("data/input/school_averages_summary_bangalore.json"))
    parser.add_argument("--output", type=Path, default=Path("data/output/schools_analysis_with_fees.json"))
    parser.add_argument("--audit", type=Path, default=Path("data/output/fee_match_audit.json"))
    parser.add_argument("--report", type=Path, default=Path("data/output/fee_coverage_report.md"))
    args = parser.parse_args()

    school_doc = json.loads(args.schools.read_text(encoding="utf-8"))
    fees = json.loads(args.fees.read_text(encoding="utf-8"))
    schools = school_doc["schools"]
    decisions, _ = match(fees, schools)

    matched = 0
    matched_students = 0
    fee_totals = 0.0
    type_stats: dict[str, dict[str, float]] = defaultdict(lambda: {"schools": 0, "students": 0, "fee_total": 0})
    board_stats: dict[str, dict[str, float]] = defaultdict(lambda: {"schools": 0, "students": 0, "fee_total": 0})
    management_stats: dict[str, dict[str, float]] = defaultdict(lambda: {"schools": 0, "students": 0, "fee_total": 0})
    band_stats: dict[str, dict[str, float]] = defaultdict(lambda: {"schools": 0, "students": 0, "fee_total": 0})
    method_counts = Counter()
    confidence_counts = Counter()
    for decision in decisions:
        if decision["status"] != "matched": continue
        fee = fees[decision["fee_index"]]
        school = schools[decision["school_index"]]
        annual_fee = fee.get("Average Fee (Annual)")
        fee_type = "Estimated" if str(fee.get("Is Fee Estimated")).strip().lower() == "yes" else "Published / not estimated"
        info = {
            "average_annual_fee": annual_fee,
            "fee_type": fee_type,
            "is_fee_estimated": fee_type == "Estimated",
            "source_board": text(fee.get("Board")),
            "source_url": text(fee.get("URL")),
            "student_teacher_ratio": text(fee.get("Student-Teacher Ratio")),
            "source_student_count": fee.get("Computed Student Count"),
            "is_source_student_count_estimated": str(fee.get("Is Student Count Estimated")).strip().lower() == "yes",
            "starting_class": text(fee.get("Starting Class")),
            "ending_class": text(fee.get("Ending Class")),
            "match": {key: value for key, value in decision.items() if key not in {"fee_index", "school_index", "status"}},
        }
        school["fee_information"] = info
        matched += 1
        students = int(school.get("enrollment", {}).get("total_students") or 0)
        matched_students += students
        if isinstance(annual_fee, (int, float)): fee_totals += annual_fee
        stat = type_stats[fee_type]
        stat["schools"] += 1; stat["students"] += students
        if isinstance(annual_fee, (int, float)): stat["fee_total"] += annual_fee
        source_board = text(fee.get("Board")) or "Unspecified"
        management = text(school["metadata"].get("management")) or "Unspecified"
        if isinstance(annual_fee, (int, float)):
            if annual_fee < 50_000: band = "Below ₹50,000"
            elif annual_fee < 100_000: band = "₹50,000–₹99,999"
            elif annual_fee < 200_000: band = "₹1–1.99 lakh"
            elif annual_fee < 500_000: band = "₹2–4.99 lakh"
            else: band = "₹5 lakh and above"
        else: band = "Fee unavailable"
        for stats, label in ((board_stats, source_board), (management_stats, management), (band_stats, band)):
            target = stats[label]; target["schools"] += 1; target["students"] += students
            if isinstance(annual_fee, (int, float)): target["fee_total"] += annual_fee
        method_counts[decision["method"]] += 1
        confidence_counts["High (≥0.75)"] += decision["confidence"] >= 0.75
        confidence_counts["Medium (0.60–0.74)"] += 0.60 <= decision["confidence"] < 0.75
        confidence_counts["Review (<0.60)"] += decision["confidence"] < 0.60

    status_counts = Counter(item["status"] for item in decisions)
    school_doc["fee_coverage"] = {
        "fee_source_records": len(fees), "matched_schools": matched,
        "operational_schools": len(schools), "school_coverage_percent": round(100 * matched / len(schools), 2),
        "matched_students": matched_students,
        "total_students": school_doc["summary"]["students"],
        "student_coverage_percent": round(100 * matched_students / school_doc["summary"]["students"], 2),
        "unmatched_fee_records": status_counts["unmatched"], "ambiguous_fee_records": status_counts["ambiguous"],
    }
    args.output.write_text(json.dumps(school_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.audit.write_text(json.dumps({"summary": school_doc["fee_coverage"], "matches": decisions}, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# School Fee Matching and Coverage Report", "",
        f"- Operational UDISE schools: **{len(schools):,}**",
        f"- Fee source records: **{len(fees):,}**",
        f"- Confident school matches: **{matched:,} ({100 * matched / len(schools):.1f}% of operational schools)**",
        f"- Students attending matched schools: **{matched_students:,} ({100 * matched_students / school_doc['summary']['students']:.1f}% of students)**",
        f"- Unmatched fee records: **{status_counts['unmatched']:,}**",
        f"- Ambiguous/duplicate fee records: **{status_counts['ambiguous']:,}**", "",
        "## Coverage by fee type", "",
        "| Fee type | Matched schools | Students | Average annual fee |", "|---|---:|---:|---:|",
    ]
    for label, stat in sorted(type_stats.items(), key=lambda item: -item[1]["schools"]):
        average = stat["fee_total"] / stat["schools"] if stat["schools"] else 0
        lines.append(f"| {label} | {int(stat['schools']):,} | {int(stat['students']):,} | ₹{average:,.0f} |")
    for heading, stats in (
        ("Coverage by annual fee band", band_stats),
        ("Coverage by source board", board_stats),
        ("Coverage by UDISE management", management_stats),
    ):
        lines.extend(["", f"## {heading}", "", "| Category | Matched schools | Students | Average annual fee |", "|---|---:|---:|---:|"])
        for label, stat in sorted(stats.items(), key=lambda item: -item[1]["schools"]):
            average = stat["fee_total"] / stat["schools"] if stat["schools"] else 0
            lines.append(f"| {label.replace('|','/')} | {int(stat['schools']):,} | {int(stat['students']):,} | ₹{average:,.0f} |")
    lines.extend(["", "## Match methods", "", "| Method | Matches |", "|---|---:|"])
    for method, count in method_counts.most_common(): lines.append(f"| {method} | {count:,} |")
    lines.extend(["", "## Match confidence", "", "| Confidence | Matches |", "|---|---:|"])
    for label, count in confidence_counts.items(): lines.append(f"| {label} | {count:,} |")
    lines.extend([
        "", "## Methodology and cautions", "",
        "- PIN-code-restricted name matching was preferred whenever the fee source supplied a valid PIN.",
        "- Missing-PIN records were matched using normalized names, coordinates, board information, and distance thresholds.",
        "- Ambiguous and duplicate candidates were excluded rather than forced.",
        "- Fee values are source averages, not audited fee schedules; the source estimation flags are retained.",
        "- UDISE enrollment totals are used for student coverage, not the fee source's estimated student counts.",
    ])
    args.report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(school_doc["fee_coverage"], indent=2))


if __name__ == "__main__":
    main()
