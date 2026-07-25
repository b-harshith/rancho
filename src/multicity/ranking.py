"""Absolute metric rankings built only from admitted validated summaries."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .config import CityRegistry
from .validators import validate_city_summary


def build_ranking(summaries: Iterable[Mapping[str, Any]], metric_id: str, *, label: str, unit: str,
                  methodology_version: str, as_of: str, registry: CityRegistry,
                  direction: str = "desc", minimum_coverage_pct: float = 0.0) -> dict[str, Any]:
    if direction not in {"asc", "desc"}:
        raise ValueError("direction must be 'asc' or 'desc'")
    if not 0 <= minimum_coverage_pct <= 100:
        raise ValueError("minimum_coverage_pct must be between 0 and 100")
    rows = []
    seen = set()
    for summary in summaries:
        validate_city_summary(summary, registry)
        city_id = summary["canonical_city_id"]
        if city_id in seen:
            raise ValueError(f"duplicate city summary: {city_id}")
        seen.add(city_id)
        if summary["admission_status"] != "admitted":
            continue
        metric = summary["metrics"].get(metric_id)
        if metric is None:
            continue
        value, coverage = metric["value"], metric["coverage_pct"]
        qualified = value is not None and coverage is not None and coverage >= minimum_coverage_pct
        status = "qualified" if qualified else ("unavailable" if value is None else "insufficient_coverage")
        rows.append({"canonical_city_id": city_id, "value": value, "rank": None,
                     "coverage_pct": coverage, "quality_status": status,
                     "source_count": metric.get("source_count"), "lineage": metric.get("lineage", summary["lineage"])})
    qualified_rows = [row for row in rows if row["quality_status"] == "qualified"]
    qualified_rows.sort(key=lambda row: ((-row["value"] if direction == "desc" else row["value"]),
                                         row["canonical_city_id"]))
    previous = object()
    for position, row in enumerate(qualified_rows, 1):
        if row["value"] != previous:
            rank = position
            previous = row["value"]
        row["rank"] = rank
    unqualified = sorted((row for row in rows if row["quality_status"] != "qualified"),
                         key=lambda row: row["canonical_city_id"])
    return {"schema_version": "1.0.0", "metric_id": metric_id, "label": label, "unit": unit,
            "metric_type": "absolute", "direction": direction,
            "methodology_version": methodology_version, "as_of": as_of,
            "minimum_coverage_pct": minimum_coverage_pct, "ranking_policy": "competition",
            "rows": qualified_rows + unqualified}
