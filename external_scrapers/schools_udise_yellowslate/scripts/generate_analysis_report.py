#!/usr/bin/env python3
"""Generate an analytical Markdown report from schools_analysis.json."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


NA_VALUES = {"", "NA", "N/A", "NONE", "NULL", "NOT APPLICABLE", "0-NA"}


def normalize(value: Any, fallback: str = "Unspecified") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    if text.upper() in NA_VALUES:
        return fallback
    return re.sub(r"^\d+\s*[-–]\s*", "", text).strip() or fallback


def board_name(school: dict[str, Any]) -> str:
    board = school["metadata"].get("board_affiliation") or {}
    secondary = normalize(board.get("secondary"))
    higher = normalize(board.get("higher_secondary"))
    values = [value for value in (secondary, higher) if value != "Unspecified"]
    return " / ".join(dict.fromkeys(values)) if values else "Unspecified / not applicable"


def enrollment_total(school: dict[str, Any]) -> int | None:
    return school.get("enrollment", {}).get("total_students")


def management_sector(school: dict[str, Any]) -> str:
    management = normalize(school["metadata"].get("management"))
    lowered = management.lower()
    if "unaided" in lowered or any(term in lowered for term in ("private", "unrecognized", "madrasa")):
        return "Private / Other"
    if "aided" in lowered:
        return "Government Aided"
    if management == "Unspecified":
        return management
    return "Government Managed"


def school_type(school: dict[str, Any]) -> str:
    value = normalize(school["metadata"].get("school_type"))
    return "Co-educational" if value.lower() in {"co-ed", "co-educational"} else value


def aggregate(
    schools: list[dict[str, Any]], classifier: Callable[[dict[str, Any]], str]
) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, int]] = defaultdict(
        lambda: {"schools": 0, "with_enrollment": 0, "students": 0, "pre_primary": 0}
    )
    for school in schools:
        group = groups[classifier(school)]
        group["schools"] += 1
        total = enrollment_total(school)
        if total is not None:
            group["with_enrollment"] += 1
            group["students"] += int(total)
        for grade in school.get("enrollment", {}).get("by_class", []):
            if grade.get("class_level") == "PRE_PRIMARY":
                group["pre_primary"] += int(grade.get("total") or 0)
                break
    rows = []
    for label, values in groups.items():
        rows.append({
            "label": label,
            **values,
            "coverage": values["with_enrollment"] / values["schools"] if values["schools"] else 0,
            "average": values["students"] / values["with_enrollment"] if values["with_enrollment"] else 0,
        })
    return sorted(rows, key=lambda item: (-item["schools"], item["label"]))


def number(value: int | float) -> str:
    return f"{value:,.0f}"


def table(rows: list[dict[str, Any]], limit: int | None = None) -> str:
    if limit:
        rows = rows[:limit]
    lines = [
        "| Category | Schools | With enrollment | Coverage | Students (Classes 1–12) | Pre-primary | Avg students |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['label'].replace('|', '/')} | {number(row['schools'])} | "
            f"{number(row['with_enrollment'])} | {row['coverage']:.1%} | "
            f"{number(row['students'])} | {number(row['pre_primary'])} | {number(row['average'])} |"
        )
    return "\n".join(lines)


def generate(input_path: Path, output_path: Path) -> None:
    document = json.loads(input_path.read_text(encoding="utf-8"))
    schools = document["schools"]
    total_schools = len(schools)
    with_enrollment = sum(enrollment_total(school) is not None for school in schools)
    students = sum(int(enrollment_total(school) or 0) for school in schools)
    pre_primary = sum(
        int(grade.get("total") or 0)
        for school in schools
        for grade in school.get("enrollment", {}).get("by_class", [])
        if grade.get("class_level") == "PRE_PRIMARY"
    )

    status_rows = aggregate(schools, lambda s: normalize(s["metadata"].get("status")))
    management_rows = aggregate(schools, lambda s: normalize(s["metadata"].get("management")))
    management_sector_rows = aggregate(schools, management_sector)
    board_rows = aggregate(schools, board_name)
    category_rows = aggregate(schools, lambda s: normalize(s["metadata"].get("category")))
    type_rows = aggregate(schools, school_type)
    district_rows = aggregate(
        schools, lambda s: normalize((s["metadata"].get("location") or {}).get("district"))
    )
    medium_rows = aggregate(
        schools,
        lambda s: ", ".join(normalize(value) for value in s["metadata"].get("mediums_of_instruction", []))
        or "Unspecified",
    )

    by_class: dict[str, dict[str, int]] = defaultdict(lambda: {"boys": 0, "girls": 0, "total": 0})
    for school in schools:
        for grade in school.get("enrollment", {}).get("by_class", []):
            level = str(grade.get("class_level"))
            by_class[level]["boys"] += int(grade.get("boys") or 0)
            by_class[level]["girls"] += int(grade.get("girls") or 0)
            by_class[level]["total"] += int(grade.get("total") or 0)
    class_order = ["PRE_PRIMARY", *map(str, range(1, 13))]
    class_lines = ["| Class | Boys | Girls | Total |", "|---|---:|---:|---:|"]
    for level in class_order:
        values = by_class[level]
        class_lines.append(
            f"| {level.replace('_', ' ').title()} | {number(values['boys'])} | "
            f"{number(values['girls'])} | {number(values['total'])} |"
        )

    operational = next((row for row in status_rows if row["label"].lower() == "operational"), None)
    government = next(
        (row["schools"] for row in management_sector_rows if row["label"] == "Government Managed"), 0
    )
    quality_counts: dict[str, int] = defaultdict(int)
    mismatch_count = 0
    for school in schools:
        quality_counts[school.get("data_quality", {}).get("status", "unknown")] += 1
        meta = school["metadata"]
        if str(meta.get("searched_pincode") or "") != str(meta.get("reported_pincode") or ""):
            mismatch_count += 1

    lines = [
        "# UDISE+ School and Enrollment Analysis",
        "",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## Executive summary",
        "",
        f"- Schools: **{number(total_schools)}**",
        f"- Schools with enrollment totals: **{number(with_enrollment)} ({with_enrollment / total_schools:.1%})**",
        f"- Students in Classes 1–12: **{number(students)}**",
        f"- Pre-primary students (reported separately): **{number(pre_primary)}**",
        f"- Operational schools: **{number(operational['schools'] if operational else 0)}**",
        f"- Government-managed schools: **{number(government)}**",
        f"- Complete analytical records: **{number(quality_counts['complete'])}**",
        f"- Partial analytical records: **{number(quality_counts['partial'])}**",
        "",
        "## School status",
        "", table(status_rows),
        "", "## Management sector", "", table(management_sector_rows),
        "", "## Detailed management", "", table(management_rows),
        "", "## Board affiliation", "",
        "Board is reported only where applicable, mainly for secondary and higher-secondary schools.",
        "", table(board_rows),
        "", "## School category", "", table(category_rows),
        "", "## School type", "", table(type_rows),
        "", "## Enrollment by class", "", "\n".join(class_lines),
        "", "## District distribution", "", table(district_rows, limit=25),
        "", "## Medium of instruction", "", table(medium_rows, limit=25),
        "", "## Data-quality notes", "",
        f"- **{number(mismatch_count)}** records have different searched and reported PIN codes.",
        "- `partial` means at least one API section was unavailable; available metadata and enrollment were retained.",
        "- UDISE enrollment totals exclude pre-primary. Pre-primary is therefore shown separately.",
        "- Zero enrollment is preserved as zero; missing enrollment is represented as null in the source JSON.",
        "- Board affiliation marked ‘Unspecified / not applicable’ should not be interpreted as a school error.",
        "- The district table is useful for spotting geographic anomalies in the source response.",
    ]
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/output/schools_analysis.json"))
    parser.add_argument("--output", type=Path, default=Path("data/output/school_analysis_report.md"))
    args = parser.parse_args()
    generate(args.input, args.output)
    print(args.output)


if __name__ == "__main__":
    main()
