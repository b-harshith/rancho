#!/usr/bin/env python3
"""Deterministically reconstruct Bengaluru artifacts in an isolated staging tree."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path

VERSION = "1.0.0"
CONTEXT_FIELDS = (
    "nearby_family_tam_weighted_context",
    "society_cluster_tam_weighted_context_not_counted",
    "surrounding_affluent_cluster_tam_weighted_context_not_counted",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def atomic_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def num(value) -> float:
    return float(value or 0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="pipelines/bengaluru_rebuild/input_manifest.json")
    parser.add_argument("--output", default="data/staging/bengaluru/current")
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()
    root, output = Path(args.repo_root).resolve(), Path(args.output).resolve()
    manifest_path = (root / args.manifest).resolve() if not Path(args.manifest).is_absolute() else Path(args.manifest)
    manifest = load(manifest_path)
    if manifest.get("status") != "READY":
        raise SystemExit(f"BLOCKED manifest: {manifest.get('status')}")

    inputs = {}
    for name, spec in manifest["inputs"].items():
        path = (root / spec["path"]).resolve()
        actual = sha256(path)
        if actual != spec["sha256"]:
            raise SystemExit(f"input hash mismatch for {name}: expected {spec['sha256']}, got {actual}")
        inputs[name] = path

    source_master, source_geo, societies = load(inputs["master"]), load(inputs["geometry"]), load(inputs["residential"])
    records = source_master["hexes"]
    by_hex = {row["hex_id"]: row for row in records}
    geometry = {f["properties"]["hex_id"]: f["geometry"] for f in source_geo["features"]}
    if len(by_hex) != len(records) or set(by_hex) != set(geometry):
        raise SystemExit("master/geometry H3 identifiers are not one-to-one")

    master = {
        "metadata": {**source_master.get("metadata", {}), "rebuild_version": VERSION, "hex_count": len(records)},
        "schema_notes": source_master.get("schema_notes", {}),
        "hexes": records,
    }
    features = []
    for hex_id in sorted(by_hex):
        row, tam = by_hex[hex_id], by_hex[hex_id].get("tam", {})
        properties = {k: v for k, v in row.items() if not isinstance(v, (dict, list))}
        properties.update({k: tam.get(k, 0) for k in ("countable_family_tam", "direct_family_tam", "direct_total_units", *CONTEXT_FIELDS)})
        features.append({"type": "Feature", "geometry": geometry[hex_id], "properties": properties})
    geojson = {"type": "FeatureCollection", "features": features}

    sums = {field: sum(num(row.get("tam", {}).get(field)) for row in records) for field in ("countable_family_tam", "direct_family_tam", "direct_total_units", *CONTEXT_FIELDS)}
    residential_hex_ids = {row.get("hex_id") for row in societies if row.get("hex_id")}
    report = {
        "city_id": "bengaluru",
        "generator_version": VERSION,
        "hex_count": len(records),
        "h3_resolution": 7,
        "countable_totals": {k: sums[k] for k in ("countable_family_tam", "direct_family_tam", "direct_total_units")},
        "context_only_totals_not_counted": {k: sums[k] for k in CONTEXT_FIELDS},
        "tier_counts": dict(sorted(Counter(row.get("affluence_tier", "Unknown") for row in records).items())),
        "residential": {
            "record_count": len(societies),
            "records_with_hex_id": sum(bool(row.get("hex_id")) for row in societies),
            "unique_hex_count": len({row.get("hex_id") for row in societies if row.get("hex_id")}),
            "hex_ids_inside_master": len(residential_hex_ids & set(by_hex)),
            "hex_ids_outside_master": len(residential_hex_ids - set(by_hex)),
            "tam_sum": sum(num(row.get("tam")) for row in societies),
            "units_sum": sum(num(row.get("units")) for row in societies),
        },
    }
    summary = {
        "city_id": "bengaluru",
        "generated_from": ["hexes_master.json", "hexes.geojson", "residential.json", "report.json"],
        "hex_count": report["hex_count"],
        "countable_family_tam": sums["countable_family_tam"],
        "direct_family_tam": sums["direct_family_tam"],
        "direct_total_units": sums["direct_total_units"],
        "context_tam_excluded": True,
        "residential_record_count": len(societies),
        "residential_hex_ids_outside_master": report["residential"]["hex_ids_outside_master"],
    }

    payloads = {"hexes_master.json": master, "hexes.geojson": geojson, "residential.json": societies, "report.json": report, "client_summary.json": summary}
    for name, payload in payloads.items():
        atomic_json(output / name, payload)
    output_hashes = {name: sha256(output / name) for name in sorted(payloads)}
    run_manifest = {"city_id": "bengaluru", "status": "BUILT_NOT_ADMITTED", "generator_version": VERSION, "input_manifest_sha256": sha256(manifest_path), "input_hashes": {k: sha256(v) for k, v in inputs.items()}, "output_hashes": output_hashes, "counts": {"hexes": len(records), "residential": len(societies)}}
    atomic_json(output / "run_manifest.json", run_manifest)
    print(json.dumps(run_manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
