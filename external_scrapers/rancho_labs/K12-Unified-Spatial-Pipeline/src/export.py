"""Export master CSV, JSON, and GeoJSON outputs."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.config import PipelineConfig
from src.progress import ProgressLogger


def export_results(
    df: pd.DataFrame,
    config: PipelineConfig,
    log: ProgressLogger | None = None,
) -> dict[str, Path]:
    """Write master CSV, JSON, and GeoJSON files. Returns output paths."""
    log = log or ProgressLogger("Export")
    log.stage("Export", config.output_dir.name)

    csv_path = config.master_csv_path
    json_path = config.master_json_path
    geojson_path = config.master_geojson_path

    df.to_csv(csv_path, index=False)
    log.success(f"CSV  → {csv_path}")

    records = df.where(pd.notna(df), None).to_dict(orient="records")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    log.success(f"JSON → {json_path}")

    features = []
    for _, row in df.iterrows():
        poly_str = row.get("Boundary_Polygon")
        if not isinstance(poly_str, str) or len(poly_str) < 10:
            continue
        try:
            ring = json.loads(poly_str)
            coords = [[pt[1], pt[0]] for pt in ring]  # GeoJSON: [lon, lat]
            if coords[0] != coords[-1]:
                coords.append(coords[0])
        except Exception:
            continue

        lat = row.get("Latitude")
        lon = row.get("Longitude")
        props = {
            k: (None if pd.isna(v) else v)
            for k, v in row.items()
            if k != "Boundary_Polygon"
        }
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [coords]},
            "properties": props,
        })

    geojson = {"type": "FeatureCollection", "features": features}
    with open(geojson_path, "w", encoding="utf-8") as f:
        json.dump(geojson, f, indent=2, ensure_ascii=False)
    log.success(f"GeoJSON → {geojson_path} ({len(features)} features)")

    return {"csv": csv_path, "json": json_path, "geojson": geojson_path}
