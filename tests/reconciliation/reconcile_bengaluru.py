#!/usr/bin/env python3
"""Independent-style cross-artifact reconciliation; exits nonzero on any drift."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

CONTEXT_FIELDS = (
    "nearby_family_tam_weighted_context",
    "society_cluster_tam_weighted_context_not_counted",
    "surrounding_affluent_cluster_tam_weighted_context_not_counted",
)


def load(path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def close(a, b):
    return math.isclose(float(a), float(b), rel_tol=0, abs_tol=1e-6)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging", default="data/staging/bengaluru/current")
    args = parser.parse_args()
    root = Path(args.staging)
    master, geo, report, summary, residential = (load(root / name) for name in ("hexes_master.json", "hexes.geojson", "report.json", "client_summary.json", "residential.json"))
    rows, features = master["hexes"], geo["features"]
    master_ids = [row["hex_id"] for row in rows]
    geo_ids = [f["properties"]["hex_id"] for f in features]
    errors = []
    if len(master_ids) != len(set(master_ids)): errors.append("duplicate H3 IDs in master")
    if len(geo_ids) != len(set(geo_ids)): errors.append("duplicate H3 IDs in GeoJSON")
    if set(master_ids) != set(geo_ids): errors.append("master/GeoJSON H3 ID sets differ")
    if report["hex_count"] != len(rows) or summary["hex_count"] != len(rows): errors.append("H3 count differs across master/report/summary")

    geo_by_id = {f["properties"]["hex_id"]: f["properties"] for f in features}
    for field in ("countable_family_tam", "direct_family_tam", "direct_total_units"):
        master_sum = sum(float(row.get("tam", {}).get(field) or 0) for row in rows)
        geo_sum = sum(float(props.get(field) or 0) for props in geo_by_id.values())
        if not close(master_sum, geo_sum): errors.append(f"{field} master/GeoJSON mismatch")
        if not close(master_sum, report["countable_totals"][field]): errors.append(f"{field} master/report mismatch")
        if not close(master_sum, summary[field]): errors.append(f"{field} master/summary mismatch")
    for field in CONTEXT_FIELDS:
        context_sum = sum(float(row.get("tam", {}).get(field) or 0) for row in rows)
        if not close(context_sum, report["context_only_totals_not_counted"][field]): errors.append(f"{field} context mismatch")
        if field in report["countable_totals"] or field in summary: errors.append(f"context field {field} leaked into countable totals")
    if summary.get("context_tam_excluded") is not True: errors.append("summary does not affirm contextual TAM exclusion")
    if report["residential"]["record_count"] != len(residential) or summary["residential_record_count"] != len(residential): errors.append("residential count mismatch")
    residential_ids = {row.get("hex_id") for row in residential if row.get("hex_id")}
    outside = residential_ids - set(master_ids)
    if report["residential"]["hex_ids_outside_master"] != len(outside): errors.append("residential outside-footprint coverage mismatch")
    if summary["residential_hex_ids_outside_master"] != len(outside): errors.append("summary outside-footprint coverage mismatch")
    result = {"status": "FAIL" if errors else "PASS", "errors": errors, "counts": {"master_hexes": len(rows), "geojson_hexes": len(features), "residential_records": len(residential), "residential_hex_ids_outside_master": len(outside)}, "note": "Contextual nearby/cluster TAM was reconciled separately and excluded from all countable totals. Residential H3 IDs outside the intelligence footprint are retained and disclosed as coverage, not added to H3 aggregates."}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
