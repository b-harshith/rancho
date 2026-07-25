#!/usr/bin/env python3
"""Release gate for retired synthetic school-market fields."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN = (
    "countable_school_age_families",
    "school_age_children_base",
    "school_age_children",
    "countable_school_age_children",
    "estimated_school_age_children",
    "countable_wealthy_school_children",
    "estimated_wealthy_school_children",
    "wealthy_school_children",
    "total_wealthy_school_children",
    "kids_tam",
    "target_student_tam",
    "reachable_student_pool",
    "student_implied_families",
    "reachable_student_implied_families",
    "families_with_kids_tam",
    "q4_families_with_kids_tam",
    "school_access_score",
    "residential_school_fit_score",
    "eligible_school_routes_count",
    "eligible_route_count",
    "effective_school_score_count",
    "feeding_schools",
)

SCANNED = (
    "src/public/data",
    "src/static/data",
    "src/public/reports",
    "DATA/final",
    "DATA/processed",
    "DATA/client_handoff",
    "src/public/index.html",
    "src/public/index.js",
    "src/public/explainer.html",
    "src/api/catchment.py",
    "src/server.py",
)

SUFFIXES = {".json", ".geojson", ".csv", ".md", ".html", ".js", ".py"}
CANONICAL_NAMES = {
    "school_entities.json",
    "school_campuses.json",
    "school_market_summary.json",
    "school_market_audit.json",
}


def files_to_scan():
    for relative in SCANNED:
        path = ROOT / relative
        if path.is_file():
            yield path
            continue
        if not path.exists():
            continue
        for candidate in path.rglob("*"):
            if candidate.is_file() and candidate.suffix.lower() in SUFFIXES:
                if candidate.name not in CANONICAL_NAMES:
                    yield candidate


def main() -> None:
    violations = []
    for path in files_to_scan():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        matches = sorted(term for term in FORBIDDEN if term in text)
        if matches:
            violations.append({"path": str(path.relative_to(ROOT)), "terms": matches})
    if violations:
        raise SystemExit("Retired school metrics remain:\n" + json.dumps(violations, indent=2))
    print("No retired school metrics found in active release artifacts.")


if __name__ == "__main__":
    main()
