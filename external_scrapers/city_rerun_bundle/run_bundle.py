#!/usr/bin/env python3
"""Run the end-to-end city rerun bundle from raw scrape to final KML package."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def read_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve_path(value: str | None) -> str | None:
    if not value:
        return None
    candidate = Path(value)
    if candidate.is_absolute():
        return str(candidate)
    return str((ROOT / candidate).resolve())


def build_base_env(config: dict, emit_html_maps: bool) -> dict[str, str]:
    city_slug = config["city_slug"]
    city_name = config.get("city_name", city_slug.replace("-", " ").title())
    env = os.environ.copy()
    env.update(
        {
            "CITY_SLUG": city_slug,
            "CITY_NAME": city_name,
            "CITY_GEOCODE_CONTEXT": config.get("city_geocode_context", city_name),
            "CITY_BOUNDARY_CONTEXT": config.get(
                "city_boundary_context",
                f"{city_name}, Karnataka, India",
            ),
            "CITY_MAP_CENTER_JSON": json.dumps(config.get("city_map_center", [12.9716, 77.5946])),
            "CITY_METRO_BOUNDS_JSON": json.dumps(
                config.get(
                    "city_metro_bounds",
                    {
                        "min_lat": 12.65,
                        "max_lat": 13.40,
                        "min_lon": 77.20,
                        "max_lon": 78.05,
                    },
                )
            ),
            "CITY_ZONE_NAMES_JSON": json.dumps(config.get("city_zone_names", [])),
            "OSRM_URL": config.get("osrm_url", "http://localhost:5001"),
            "COOKIE_HEADER": config.get("99acres_cookie_header", ""),
            "SEZ_KML_PATH": resolve_path(config.get("sez_kml_path", "data/Stage2 processing/sez_office_zones.kml")) or "",
            "OVERTURE_BUILDINGS_PATH": resolve_path(
                config.get(
                    "overture_buildings_path",
                    f"data/overture/{city_slug}_buildings.geojson",
                )
            )
            or "",
            "EMIT_HTML_MAPS": "1" if emit_html_maps else "0",
            "PYTHONUNBUFFERED": "1",
        }
    )
    return env


def run_step(label: str, argv: list[str], env: dict[str, str]) -> None:
    print(f"\n==> {label}", flush=True)
    subprocess.run([sys.executable, *argv], cwd=ROOT, env=env, check=True)


def run_shell_step(label: str, argv: list[str], env: dict[str, str]) -> None:
    print(f"\n==> {label}", flush=True)
    subprocess.run(argv, cwd=ROOT, env=env, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default="config/bangalore.json",
        help="City profile JSON file relative to the bundle root.",
    )
    parser.add_argument(
        "--emit-html-maps",
        action="store_true",
        help="Also generate the intermediate HTML heatmaps and exploratory map layers.",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = ROOT / config_path
    config = read_config(config_path)

    city_slug = config["city_slug"]
    city_name = config.get("city_name", city_slug.replace("-", " ").title())
    base_env = build_base_env(config, emit_html_maps=args.emit_html_maps or config.get("emit_html_maps", False))

    locality_raw_json = ROOT / "data" / "raw" / f"99acres_{city_slug}_localities.json"
    locality_raw_jsonl = ROOT / "data" / "raw" / f"99acres_{city_slug}_localities.jsonl"
    society_raw_json = ROOT / "data" / f"99acres_{city_slug}_societies.json"
    society_raw_jsonl = ROOT / "data" / "raw" / f"99acres_{city_slug}_societies.jsonl"

    steps: list[tuple[str, list[str], dict[str, str]]] = [
        (
            "Scrape 99acres localities",
            ["scripts/source/locality/scrape_99acres_localities.py"],
            {
                "TARGET_URL": config["99acres_locality_target_url"],
                "API_CITY_ID": config["99acres_locality_api_city_id"],
            },
        ),
        (
            "Flatten locality JSONL",
            [
                "scripts/shared/flatten_jsonl_records.py",
                "--input",
                str(locality_raw_jsonl),
                "--output",
                str(locality_raw_json),
            ],
            {},
        ),
        ("Restructure locality JSON", ["scripts/source/locality/restructure_json.py"], {}),
        ("Estimate income brackets", ["scripts/source/locality/estimate_income_brackets.py"], {}),
        ("Predict budget range", ["scripts/source/locality/predict_budget_range.py"], {}),
        ("Fetch locality coordinates", ["scripts/source/locality/fetch_locality_coordinates.py"], {}),
        ("Merge coordinates", ["scripts/source/locality/merge_coordinates.py"], {}),
        ("Fetch locality boundaries", ["scripts/source/locality/fetch_locality_boundaries.py"], {}),
        ("Fetch Overture boundaries", ["scripts/source/locality/fetch_overture_boundaries.py"], {}),
        ("Assign neighborhoods", ["scripts/source/locality/assign_neighborhoods.py"], {}),
        ("Refine assignments", ["scripts/source/locality/refine_assignments.py"], {}),
        ("Merge locality data", ["scripts/source/locality/merge_locality_data.py"], {}),
        ("Run school pipeline", ["scripts/source/schools/run_pipeline.py", "--city", city_name], {}),
        ("Categorize schools", ["scripts/source/schools/generate_q4_categories.py"], {}),
        (
            "Scrape 99acres societies",
            ["scripts/source/societies/scrape_99acres_societies.py"],
            {
                "TARGET_URL": config["99acres_society_target_url"],
                "API_CITY_ID": config["99acres_society_api_city_id"],
            },
        ),
        (
            "Flatten society JSONL",
            [
                "scripts/shared/flatten_jsonl_records.py",
                "--input",
                str(society_raw_jsonl),
                "--output",
                str(society_raw_json),
            ],
            {},
        ),
        ("Categorize societies", ["scripts/source/societies/generate_society_q4.py"], {}),
        ("Scrape society details", ["scripts/source/societies/scrape_society_details.py"], {}),
        ("Scrape hospitals", ["scripts/source/hospitals/practo_hospitals_scraper.py"], {}),
        ("Categorize hospitals", ["scripts/source/hospitals/generate_hospital_q4.py"], {}),
        ("Build H3 base cells", ["scripts/analysis/generate_h3_heatmaps.py"], {}),
        ("Export stage 1 locality features", ["scripts/analysis/export_stage1_locality_features.py"], {}),
        ("Build stage 1.5 hex-7 features", ["scripts/analysis/generate_stage15_h3_res7.py"], {}),
        (
            "Build stage 2 hex-7 affluence",
            ["scripts/analysis/generate_stage2_hex7_affluence.py"],
            {},
        ),
        (
            "Build final hex intelligence package",
            ["scripts/analysis/generate_final_hex_intelligence.py"],
            {},
        ),
    ]

    print(f"Running bundle for {city_name} ({city_slug})", flush=True)
    for label, argv, overrides in steps:
        env = base_env.copy()
        env.update(overrides)
        run_step(label, argv, env)

    print("\nBundle run completed.", flush=True)
    print(f"Final deliverables should now live under {ROOT / 'data' / 'final'} and {ROOT / 'maps' / 'final'}.", flush=True)


if __name__ == "__main__":
    main()
