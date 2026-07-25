#!/usr/bin/env python3
"""Remove retired synthetic school metrics from published/generated artifacts.

The canonical school-market outputs are intentionally excluded. This script is a
release guard for the older affluence pipeline, whose historical outputs embedded
modeled children and school-access fields in every H3 record.
"""

from __future__ import annotations

import csv
import json
import os
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent

RETIRED_KEYS = {
    "countable_school_age_families",
    "school_age_children_base",
    "school_age_children",
    "countable_school_age_children",
    "estimated_school_age_children",
    "countable_wealthy_school_children",
    "estimated_wealthy_school_children",
    "wealthy_school_children",
    "wealthy_school_children_source",
    "total_wealthy_school_children",
    "kids_tam",
    "target_grade_2_9_kids",
    "target_student_tam",
    "student_implied_families",
    "reachable_grade_2_9_kids",
    "reachable_student_implied_families",
    "reachable_student_pool",
    "families_with_kids_tam",
    "q4_families_with_kids_tam",
    "school_score",
    "school_access_score",
    "residential_school_fit_score",
    "eligible_school_routes_count",
    "eligible_route_count",
    "effective_school_score_count",
    "feeding_schools",
    "top_schools",
    "school_summary",
    "schools_nearby_count",
}

RETIRED_TEXT_TERMS = tuple(sorted(RETIRED_KEYS | {
    "wealthy school children",
    "wealthy-school children",
    "student-implied families",
    "school-access-adjusted",
}))

JSON_GLOBS = (
    "src/public/data/*.json",
    "src/public/data/*.geojson",
    "src/static/data/*.json",
    "src/static/data/*.geojson",
    "src/public/reports/*.json",
    "DATA/final/*.json",
    "DATA/final/*.geojson",
    "DATA/processed/*.json",
    "DATA/processed/*.geojson",
    "DATA/audits/*.json",
    "DATA/client_handoff/*.json",
)

CSV_GLOBS = (
    "DATA/final/*.csv",
    "DATA/processed/*.csv",
)

TEXT_GLOBS = (
    "DATA/final/*.md",
    "DATA/audits/*.md",
    "DATA/client_handoff/*.md",
    "src/public/reports/*.md",
)

CANONICAL_PREFIXES = ("school_entities", "school_campuses", "school_market_")


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def sanitize_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: sanitize_json_value(item)
            for key, item in value.items()
            if key not in RETIRED_KEYS
        }
    if isinstance(value, list):
        return [
            sanitize_json_value(item)
            for item in value
            if not (isinstance(item, dict) and item.get("poi_type") == "school")
        ]
    return value


def sanitize_json(path: Path) -> bool:
    if path.name.startswith(CANONICAL_PREFIXES):
        return False
    raw = path.read_text(encoding="utf-8")
    if not any(term in raw for term in RETIRED_TEXT_TERMS):
        return False
    payload = json.loads(raw)
    cleaned = sanitize_json_value(payload)
    atomic_write_text(path, json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n")
    return True


def sanitize_csv(path: Path) -> bool:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            return False
        retained = [name for name in reader.fieldnames if name not in RETIRED_KEYS]
        if retained == reader.fieldnames:
            return False
        rows = [{key: row.get(key, "") for key in retained} for row in reader]

    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=retained)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    return True


def sanitize_text(path: Path) -> bool:
    lines = path.read_text(encoding="utf-8").splitlines()
    kept = [
        line
        for line in lines
        if not any(term.lower() in line.lower() for term in RETIRED_TEXT_TERMS)
    ]
    if kept == lines:
        return False
    atomic_write_text(path, "\n".join(kept).rstrip() + "\n")
    return True


def iter_paths(patterns: tuple[str, ...]):
    seen: set[Path] = set()
    for pattern in patterns:
        for path in ROOT.glob(pattern):
            if path.is_file() and path not in seen:
                seen.add(path)
                yield path


def main() -> None:
    changed: list[str] = []
    for path in iter_paths(JSON_GLOBS):
        if sanitize_json(path):
            changed.append(str(path.relative_to(ROOT)))
    for path in iter_paths(CSV_GLOBS):
        if sanitize_csv(path):
            changed.append(str(path.relative_to(ROOT)))
    for path in iter_paths(TEXT_GLOBS):
        if sanitize_text(path):
            changed.append(str(path.relative_to(ROOT)))
    print(json.dumps({"changed_count": len(changed), "changed": changed}, indent=2))


if __name__ == "__main__":
    main()
