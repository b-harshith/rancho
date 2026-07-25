#!/usr/bin/env python3
"""
Overture Maps — Multi-Layer GeoJSON Merger
==========================================
Merges all Overture Maps GeoJSON layer files in `data/overture/` into a single
FeatureCollection GeoJSON. Each feature is tagged with a `layer_type` property
derived from its source filename.

Reads files line-by-line to handle very large files (875 MB+ buildings) without
loading everything into memory at once.

Output: data/overture/bangalore_merged.geojson

Usage:
    python3 scratch/merge_overture_layers.py
    python3 scratch/merge_overture_layers.py --exclude buildings   # skip buildings (saves ~875MB)
    python3 scratch/merge_overture_layers.py --only water,land_use # merge specific layers only
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────
PROJECT_ROOT   = Path(__file__).resolve().parent.parent
OVERTURE_DIR   = PROJECT_ROOT / "data" / "overture"
OUTPUT_FILE    = OVERTURE_DIR / "bangalore_merged.geojson"

# Map from filename stem → human-readable layer type tag
LAYER_TYPE_MAP = {
    "bangalore_buildings":    "building",
    "bangalore_segments":     "segment",
    "bangalore_places":       "place",
    "bangalore_water":        "water",
    "bangalore_land_use":     "land_use",
    "bangalore_landuse":      "land_use",       # duplicate from previous runs
    "bangalore_infrastructure":"infrastructure",
    "bangalore_land":         "land",
    "bangalore_land_cover":   "land_cover",
    "bangalore_division":     "division",
}


def get_layer_type(path: Path) -> str:
    """Returns a clean layer_type string for a GeoJSON file."""
    stem = path.stem  # e.g. 'bangalore_buildings'
    return LAYER_TYPE_MAP.get(stem, stem.replace("bangalore_", ""))


def format_size(bytes_val: int) -> str:
    """Returns human-readable file size string."""
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_val < 1024:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f} TB"


def discover_layers(exclude: set, only: set) -> list[Path]:
    """
    Finds all valid, non-empty GeoJSON files in OVERTURE_DIR.
    Filters by --exclude or --only flags if provided.
    Skips duplicate files (e.g. bangalore_landuse vs bangalore_land_use).
    """
    files = sorted(OVERTURE_DIR.glob("*.geojson"))
    seen_types = set()
    result = []

    for f in files:
        # Skip output file itself
        if f == OUTPUT_FILE:
            continue
        # Skip empty files
        if f.stat().st_size == 0:
            print(f"  ⚠️  Skipping {f.name} — file is empty (0 bytes)", flush=True)
            continue
        # Skip .state companion files (not GeoJSON)
        layer_type = get_layer_type(f)
        # Apply --only filter
        if only and layer_type not in only:
            continue
        # Apply --exclude filter
        if layer_type in exclude:
            print(f"  ⏭️  Skipping {f.name} (--exclude {layer_type})", flush=True)
            continue
        # Deduplicate: if we've already seen this layer type, skip duplicates
        if layer_type in seen_types:
            print(f"  ⏭️  Skipping {f.name} — duplicate of layer '{layer_type}'", flush=True)
            continue
        seen_types.add(layer_type)
        result.append(f)

    return result


def count_lines(path: Path) -> int:
    """Fast line count using binary read."""
    count = 0
    with open(path, "rb") as f:
        for _ in f:
            count += 1
    return count


def stream_features(path: Path, layer_type: str):
    """
    Generator: yields GeoJSON feature dicts from a line-delimited or
    FeatureCollection GeoJSON file. Injects `layer_type` into each feature's
    properties before yielding.
    """
    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            # Skip FeatureCollection wrapper lines and empty lines
            if not line:
                continue
            if line.startswith('{"type": "FeatureCollection"') or line.startswith('{"type":"FeatureCollection"'):
                continue
            if line in ("]}",):
                continue
            # Strip trailing comma (line-delimited GeoJSON style)
            if line.endswith(","):
                line = line[:-1]
            # Skip bare array brackets
            if line in ("[", "]"):
                continue
            try:
                feat = json.loads(line)
                if feat.get("type") != "Feature":
                    continue
                # Inject layer_type into properties
                if feat.get("properties") is None:
                    feat["properties"] = {}
                feat["properties"]["layer_type"] = layer_type
                yield feat
            except json.JSONDecodeError:
                continue


def merge_layers(layers: list[Path], output: Path):
    """
    Streams features from each layer file and writes them to a single
    FeatureCollection GeoJSON output file.
    """
    total_features = 0
    layer_counts = {}
    global_start = time.time()

    print(f"\n{'='*70}", flush=True)
    print(f"  🗺️  OVERTURE MAPS — MULTI-LAYER GEOJSON MERGER", flush=True)
    print(f"{'='*70}", flush=True)
    print(f"  Merging {len(layers)} layer(s) → {output.name}", flush=True)
    print(f"  Output:  {output}", flush=True)
    print(f"{'='*70}\n", flush=True)

    with open(output, "w", encoding="utf-8") as out_f:
        # Write FeatureCollection header
        out_f.write('{"type": "FeatureCollection", "features": [\n')
        first_feature = True

        for layer_path in layers:
            layer_type = get_layer_type(layer_path)
            size_str   = format_size(layer_path.stat().st_size)
            layer_count = 0
            t0 = time.time()

            print(f"  📂 [{layer_type:>15s}]  Reading {layer_path.name}  ({size_str})", flush=True)

            for feat in stream_features(layer_path, layer_type):
                # Write comma separator between features
                if not first_feature:
                    out_f.write(",\n")
                else:
                    first_feature = False
                out_f.write(json.dumps(feat, separators=(",", ":")))
                layer_count += 1
                total_features += 1

                # Live progress every 50,000 features
                if layer_count % 50_000 == 0:
                    elapsed = time.time() - t0
                    rate = layer_count / elapsed if elapsed > 0 else 0
                    print(f"             → {layer_count:>8,} features  ({rate:,.0f} feat/s)", flush=True)

            elapsed = time.time() - t0
            layer_counts[layer_type] = layer_count
            print(f"             ✅ {layer_count:>8,} features written  [{elapsed:.1f}s]\n", flush=True)

        # Close FeatureCollection
        out_f.write("\n]}\n")

    total_elapsed = time.time() - global_start
    output_size   = format_size(output.stat().st_size)

    print(f"{'='*70}", flush=True)
    print(f"  ✅ MERGE COMPLETE", flush=True)
    print(f"{'='*70}", flush=True)
    print(f"  Total features written : {total_features:,}", flush=True)
    print(f"  Output file size       : {output_size}", flush=True)
    print(f"  Time elapsed           : {total_elapsed:.1f}s", flush=True)
    print(f"\n  Layer breakdown:", flush=True)
    for ltype, cnt in layer_counts.items():
        print(f"    {ltype:>20s}  →  {cnt:>8,} features", flush=True)
    print(f"{'='*70}\n", flush=True)
    print(f"  📁 Output saved to:\n     {output}", flush=True)


# ── CLI Entry Point ───────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Merge all Overture Maps GeoJSON layers into one FeatureCollection."
    )
    parser.add_argument(
        "--exclude",
        type=str,
        default="",
        help="Comma-separated list of layer types to exclude (e.g. buildings,places)."
    )
    parser.add_argument(
        "--only",
        type=str,
        default="",
        help="Comma-separated list of layer types to include (overrides --exclude)."
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(OUTPUT_FILE),
        help=f"Output file path (default: {OUTPUT_FILE})"
    )
    args = parser.parse_args()

    exclude_set = set(x.strip() for x in args.exclude.split(",") if x.strip())
    only_set    = set(x.strip() for x in args.only.split(",") if x.strip())
    output_path = Path(args.output)

    # Discover layers
    print(f"\n  🔍 Scanning {OVERTURE_DIR} for GeoJSON layers...\n", flush=True)
    layers = discover_layers(exclude=exclude_set, only=only_set)

    if not layers:
        print("  ❌ No valid GeoJSON layers found. Nothing to merge.", flush=True)
        sys.exit(1)

    # Estimate total disk space
    total_input_bytes = sum(p.stat().st_size for p in layers)
    print(f"  Found {len(layers)} layer(s), total input size: {format_size(total_input_bytes)}", flush=True)
    print(f"  Layers to merge:", flush=True)
    for p in layers:
        ltype = get_layer_type(p)
        print(f"    • [{ltype:>15s}]  {p.name}  ({format_size(p.stat().st_size)})", flush=True)

    # Warn if including buildings (very large output)
    if any(get_layer_type(p) == "building" for p in layers):
        print(f"\n  ⚠️  WARNING: The buildings layer is 875 MB. The merged file will be", flush=True)
        print(f"              very large (~{format_size(total_input_bytes)}). Consider using", flush=True)
        print(f"              --exclude buildings to skip it if you only need other layers.\n", flush=True)
        print(f"  Proceeding in 3 seconds (Ctrl+C to cancel)...\n", flush=True)
        time.sleep(3)

    # Run merge
    merge_layers(layers, output_path)


if __name__ == "__main__":
    main()
