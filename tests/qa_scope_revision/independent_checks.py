#!/usr/bin/env python3
"""Independent, offline QA checks for the 2026-06-30 scope revision."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import sys

from jsonschema import Draft202012Validator, RefResolver
from shapely.geometry import shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/collectors/fixtures"
sys.path.insert(0, str(ROOT))

from collectors.ezyschooling.collector import normalize_school, parse_detail_document, parse_page_payload
from collectors.magicbricks_localities.parser import parse_detail_page, parse_listing_page
from pipelines.schools.merge import haversine_km, reconcile


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def validate(schema_name: str, instance: dict) -> list[str]:
    schema_dir = ROOT / "schemas/multicity/v1"
    schema = json.loads((schema_dir / schema_name).read_text())
    common = json.loads((schema_dir / "common_entity.schema.json").read_text())
    resolver = RefResolver((schema_dir / schema_name).as_uri(), schema, store={common["$id"]: common})
    return [e.message for e in Draft202012Validator(schema, resolver=resolver).iter_errors(instance)]


def run() -> dict:
    results: dict = {"checks": {}}
    pins = list(csv.DictReader((ROOT / "DATA/reference/pincodes/delhi_ncr_pin_candidates.csv").open()))
    exclusions = list(csv.DictReader((ROOT / "DATA/reference/pincodes/delhi_ncr_pin_exclusions.csv").open()))
    pin_values = [r["pincode"] for r in pins]
    component_counts = {c: sum(c in r["components"].split(";") for r in pins) for c in
                        ("delhi_nct", "faridabad", "ghaziabad", "gurugram", "noida_greater_noida")}
    results["checks"]["pins"] = {
        "rows": len(pins), "unique": len(set(pin_values)), "six_digit": all(len(x) == 6 and x.isdigit() for x in pin_values),
        "component_counts": component_counts, "cross_component": sum(len(r["components"].split(";")) > 1 for r in pins),
        "excluded_rows": len(exclusions), "include_exclude_overlap": sorted(set(pin_values) & {r["pincode"] for r in exclusions}),
        "all_provenance_present": all(r["source"] and r["decision_rule"] for r in pins),
    }
    geo = json.loads((ROOT / "DATA/reference/boundaries/delhi_ncr_components.geojson").read_text())
    shapes = [shape(f["geometry"]) for f in geo["features"]]
    union = unary_union(shapes)
    results["checks"]["boundaries"] = {
        "features": len(shapes), "all_valid": all(g.is_valid for g in shapes), "union_valid": union.is_valid,
        "union_type": union.geom_type, "bounds": [round(x, 5) for x in union.bounds],
        "component_counts": {c: sum(f["properties"].get("component_id") == c for f in geo["features"]) for c in
                             ("delhi_nct", "faridabad", "ghaziabad", "gurugram", "noida_greater_noida")},
    }
    # Known equatorial one-degree arc is ~111.195 km with the selected mean-earth radius.
    h = haversine_km(0, 0, 0, 1)
    results["checks"]["haversine"] = {"equatorial_degree_km": h, "accurate": math.isclose(h, 111.19508, abs_tol=.001)}

    page = load("ezyschooling_page_delhi_ncr.json")
    detail_f = load("ezyschooling_detail_delhi_ncr.json")
    rows, total = parse_page_payload(page)
    detail = parse_detail_document(detail_f["html"], detail_f["url"])
    rows[0]["_page_raw_sha256"] = "pagehash"; detail["_raw_sha256"] = "detailhash"
    school = normalize_school(rows[0], detail, "delhi_ncr", "2026-06-30T00:00:00Z")
    collision = reconcile([
        {"source": "ezyschooling", "source_entity_id": "e1", "name": "Same School", "lat": 28.5, "lon": 77.2},
        {"source": "ezyschooling", "source_entity_id": "e2", "name": "Same School", "lat": 28.5, "lon": 77.2},
    ], [{"source_entity_id": "c1", "name": "Same School", "lat": 28.5, "lon": 77.2}], "udise")
    results["checks"]["ezyschooling"] = {
        "fixture_total": total, "school_schema_errors": validate("school.schema.json", school),
        "entity_id": school["entity_id"], "collision_statuses": sorted({x["status"] for x in collision}),
        "detail_visited": school["lineage"]["detail_stage"] == "visited",
    }

    listing_f = load("magicbricks_localities_listing.json")
    parsed = parse_listing_page(listing_f["html"], listing_f["url"])
    detail_mb = load("magicbricks_localities_detail.json")
    locality = {**parsed["records"][0], **parse_detail_page(detail_mb["html"], detail_mb["url"]),
                "canonical_city_id": "delhi_ncr"}
    results["checks"]["magicbricks"] = {
        "fixture_links": len(parsed["records"]), "detail_identity": locality.get("source_entity_id"),
        "locality_schema_errors": validate("locality.schema.json", locality),
    }
    return results


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
