"""Build Delhi NCR component boundaries and an authoritative PIN ledger."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from shapely.geometry import mapping, shape
from shapely.ops import unary_union
from shapely.validation import explain_validity

DELHI_DISTRICTS = {
    "Central",
    "East",
    "New Delhi",
    "North",
    "North East",
    "North West",
    "Shahdara",
    "South",
    "South East",
    "South West",
    "West",
}
SATELLITE_DISTRICTS = {
    "Gurgaon": "gurugram",
    "Faridabad": "faridabad",
    "Ghaziabad": "ghaziabad",
    "Gautam Buddha Nagar": "noida_greater_noida",
}
PIN_DISTRICT_ALIASES = {
    "gurgaon": "gurugram",
    "gurugram": "gurugram",
    "faridabad": "faridabad",
    "ghaziabad": "ghaziabad",
    "gautam buddha nagar": "noida_greater_noida",
    "gautam budh nagar": "noida_greater_noida",
}


def component_for_postal_row(row: dict[str, str]) -> str | None:
    normalized = {key.casefold(): value for key, value in row.items()}
    state = (normalized.get("statename") or normalized.get("state") or "").strip().casefold()
    district = (normalized.get("districtname") or normalized.get("district") or "").strip().casefold()
    if state == "delhi":
        return "delhi_nct"
    return PIN_DISTRICT_ALIASES.get(district)


def iter_postal_rows(source: Path):
    paths = sorted(source.glob("*.csv")) if source.is_dir() else [source]
    for path in paths:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                yield {key.casefold(): value for key, value in row.items()}


def build_pins(source: Path, included_path: Path, excluded_path: Path) -> dict:
    included: dict[str, dict] = {}
    all_rows = []
    included_prefixes = set()
    for row in iter_postal_rows(source):
        pin = (row.get("pincode") or "").strip()
        if len(pin) != 6 or not pin.isdigit():
            continue
        component = component_for_postal_row(row)
        all_rows.append((pin, component, row))
        if component:
            included_prefixes.add(pin[:3])
            entry = included.setdefault(
                pin,
                {"components": set(), "districts": set(), "states": set(), "offices": set(), "delivery": False},
            )
            entry["components"].add(component)
            entry["districts"].add((row.get("districtname") or row.get("district") or "").strip())
            entry["states"].add((row.get("statename") or row.get("state") or "").strip())
            entry["offices"].add((row.get("officename") or row.get("office") or "").strip())
            entry["delivery"] |= (row.get("deliverystatus") or row.get("delivery") or "").strip().casefold() == "delivery"

    included_path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["pincode", "canonical_city_id", "components", "districts", "states", "office_count", "has_delivery_office", "decision", "decision_rule", "source"]
    with included_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for pin, entry in sorted(included.items()):
            writer.writerow(
                {
                    "pincode": pin,
                    "canonical_city_id": "delhi_ncr",
                    "components": ";".join(sorted(entry["components"])),
                    "districts": ";".join(sorted(entry["districts"])),
                    "states": ";".join(sorted(entry["states"])),
                    "office_count": len(entry["offices"]),
                    "has_delivery_office": str(entry["delivery"]).lower(),
                    "decision": "include",
                    "decision_rule": "office belongs to an approved NCR component district",
                    "source": "India Post All India Pincode Directory",
                }
            )

    excluded = defaultdict(lambda: {"districts": set(), "states": set(), "offices": set()})
    for pin, component, row in all_rows:
        # Decide inclusion/exclusion only after grouping the full directory by
        # PIN. A PIN with even one approved-component office is included once
        # and must never also appear in the exclusion ledger.
        if pin not in included and not component and pin[:3] in included_prefixes:
            item = excluded[pin]
            item["districts"].add((row.get("districtname") or row.get("district") or "").strip())
            item["states"].add((row.get("statename") or row.get("state") or "").strip())
            item["offices"].add((row.get("officename") or row.get("office") or "").strip())
    with excluded_path.open("w", encoding="utf-8", newline="") as handle:
        fields = ["pincode", "districts", "states", "office_count", "decision", "reason", "candidate_universe"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for pin, entry in sorted(excluded.items()):
            writer.writerow(
                {
                    "pincode": pin,
                    "districts": ";".join(sorted(entry["districts"])),
                    "states": ";".join(sorted(entry["states"])),
                    "office_count": len(entry["offices"]),
                    "decision": "exclude",
                    "reason": "same 3-digit postal prefix as included PIN, but no office in an approved component district",
                    "candidate_universe": "adjacent_prefix_audit",
                }
            )
    component_counts = defaultdict(int)
    cross_component = 0
    for entry in included.values():
        for component in entry["components"]:
            component_counts[component] += 1
        cross_component += len(entry["components"]) > 1
    return {
        "included_unique_pins": len(included),
        "excluded_adjacent_prefix_pins": len(excluded),
        "component_pin_counts": dict(sorted(component_counts.items())),
        "cross_component_pin_count": cross_component,
        "duplicate_pincodes_in_output": 0,
    }


def build_boundaries(source: Path, output: Path) -> dict:
    data = json.loads(source.read_text(encoding="utf-8"))
    selected = []
    component_geometries = defaultdict(list)
    for feature in data["features"]:
        raw_name = feature["properties"].get("shapeName") or ""
        name = raw_name.strip()
        if name in DELHI_DISTRICTS:
            component = "delhi_nct"
        elif name in SATELLITE_DISTRICTS:
            component = SATELLITE_DISTRICTS[name]
        else:
            continue
        geometry = shape(feature["geometry"])
        if not geometry.is_valid:
            raise ValueError(f"Invalid source polygon {name}: {explain_validity(geometry)}")
        component_geometries[component].append(geometry)
        selected.append(
            {
                "type": "Feature",
                "properties": {
                    "canonical_city_id": "delhi_ncr",
                    "component_id": component,
                    "district_name": name,
                    "source_shape_id": feature["properties"].get("shapeID"),
                    "source": "geoBoundaries gbOpen IND ADM2",
                    "boundary_year": "2021",
                },
                "geometry": mapping(geometry),
            }
        )
    if len(selected) != 15 or len(component_geometries["delhi_nct"]) != 11:
        raise ValueError(f"Expected 15 district polygons including 11 Delhi NCT districts; got {len(selected)} and {len(component_geometries['delhi_nct'])}")
    union = unary_union([shape(f["geometry"]) for f in selected])
    if not union.is_valid:
        raise ValueError(f"Invalid NCR union: {explain_validity(union)}")
    output.parent.mkdir(parents=True, exist_ok=True)
    collection = {"type": "FeatureCollection", "features": selected}
    output.write_text(json.dumps(collection, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    minx, miny, maxx, maxy = union.bounds
    component_summaries = {}
    for component, geometries in sorted(component_geometries.items()):
        component_union = unary_union(geometries)
        cminx, cminy, cmaxx, cmaxy = component_union.bounds
        point = component_union.representative_point()
        component_summaries[component] = {
            "district_count": len(geometries),
            "bounds_wgs84": {"west": cminx, "south": cminy, "east": cmaxx, "north": cmaxy},
            "representative_center_wgs84": {"lat": point.y, "lon": point.x},
        }
    return {
        "district_feature_count": len(selected),
        "component_count": len(component_geometries),
        "delhi_nct_district_count": len(component_geometries["delhi_nct"]),
        "all_source_geometries_valid": True,
        "union_valid": True,
        "union_geometry_type": union.geom_type,
        "bounds_wgs84": {"west": minx, "south": miny, "east": maxx, "north": maxy},
        "representative_center_wgs84": {"lat": union.representative_point().y, "lon": union.representative_point().x},
        "component_district_counts": {k: len(v) for k, v in sorted(component_geometries.items())},
        "components": component_summaries,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--postal-source", type=Path, required=True)
    parser.add_argument("--boundary-source", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    pins_dir = args.root / "data/reference/pincodes"
    boundary_dir = args.root / "data/reference/boundaries"
    audit_dir = args.root / "data/cities/delhi_ncr/audits/geospatial"
    pin_stats = build_pins(args.postal_source, pins_dir / "delhi_ncr_pin_candidates.csv", pins_dir / "delhi_ncr_pin_exclusions.csv")
    boundary_stats = build_boundaries(args.boundary_source, boundary_dir / "delhi_ncr_components.geojson")
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit = {
        "schema_version": "1.0",
        "canonical_city_id": "delhi_ncr",
        "generated_on": date.today().isoformat(),
        "status": "prepared_open_sources_google_reference_pending",
        "pin_coverage": pin_stats,
        "boundary_coverage": boundary_stats,
        "google_conflict_check": {"status": "blocked", "reason": "GOOGLE_MAPS_API_KEY not present in runtime environment"},
    }
    (audit_dir / "preparation_report.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
