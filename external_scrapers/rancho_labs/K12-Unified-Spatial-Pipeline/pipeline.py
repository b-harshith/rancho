#!/usr/bin/env python3
"""
K12 Unified Spatial Pipeline
==============================
End-to-end spatial processing for school campuses:

  City Input → Bounding Box → Overture Download → School Geocoding
  → Footprint Matching → Campus Refinement → Master Export

Usage:
  python pipeline.py --city bangalore --schools path/to/schools.csv
  python pipeline.py --city mumbai --schools schools.csv --skip-download
  python pipeline.py --city bangalore --schools schools.csv --stage geocode
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from src.campus_refiner import run_refinement
from src.city_extent import resolve_city_extent
from src.config import LOGS_DIR, PipelineConfig
from src.export import export_results
from src.footprint import load_buildings, run_matching
from src.geocode import GeocodeCache, run_geocoding
from src.overture_download import download_overture_data
from src.progress import ProgressLogger

load_dotenv()

STAGES = ("extent", "download", "geocode", "match", "refine", "export", "all")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="K12 Unified Spatial Pipeline — automated campus boundary processing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--city", required=True, help="City name (e.g. bangalore, mumbai)")
    p.add_argument(
        "--schools", required=True, type=Path,
        help="Path to school list CSV",
    )
    p.add_argument(
        "--output", type=Path, default=None,
        help="Output directory (default: ./output)",
    )
    p.add_argument(
        "--provider", choices=["google", "arcgis", "osm"], default=None,
        help="Geocoding provider (default: google if API key set, else arcgis+osm)",
    )
    p.add_argument(
        "--stage", choices=STAGES, default="all",
        help="Run a single stage or all (default: all)",
    )
    p.add_argument("--skip-download", action="store_true", help="Skip Overture download")
    p.add_argument("--skip-geocode", action="store_true", help="Skip school geocoding")
    p.add_argument("--skip-match", action="store_true", help="Skip footprint matching")
    p.add_argument("--skip-refine", action="store_true", help="Skip campus refinement")
    return p.parse_args()


def run_pipeline(config: PipelineConfig, stage: str = "all") -> int:
    log = ProgressLogger("K12 Spatial Pipeline")
    t0 = time.time()

    log.info(f"City: {config.city} | Schools: {config.schools_csv}")
    log.info(f"Provider: {config.default_provider()}")

    if not config.schools_csv.exists():
        log.error(f"School CSV not found: {config.schools_csv}")
        return 1

    df = pd.read_csv(config.schools_csv)
    log.info(f"Loaded {len(df)} schools from CSV")

    extent = None
    run_all = stage == "all"

    # ── Stage 1: City Extent ──────────────────────────────────────────────
    if run_all or stage == "extent":
        log.stage("City Extent Resolution", config.city)
        try:
            extent = resolve_city_extent(config.city)
            log.success(str(extent))
        except ValueError as exc:
            log.error(str(exc))
            return 1
        if stage == "extent":
            return 0

    # ── Stage 2: Overture Download ────────────────────────────────────────
    if (run_all or stage == "download") and not config.skip_download:
        if extent is None:
            extent = resolve_city_extent(config.city)
        if not download_overture_data(config, extent, log):
            if not config.buildings_path.exists():
                log.error("Building data unavailable — cannot continue")
                return 1
        if stage == "download":
            return 0

    # ── Stage 3: School Geocoding ─────────────────────────────────────────
    if (run_all or stage == "geocode") and not config.skip_geocode:
        cache = GeocodeCache()
        try:
            df = run_geocoding(df, config, cache, log)
        finally:
            cache.close()
        if stage == "geocode":
            export_results(df, config, log)
            return 0

    # ── Stage 4: Footprint Matching ───────────────────────────────────────
    if (run_all or stage == "match") and not config.skip_match:
        if not config.buildings_path.exists():
            log.error(f"Buildings file not found: {config.buildings_path}")
            log.error("Run with --stage download first, or place Overture data manually")
            return 1
        index = load_buildings(config.buildings_path, log)
        df = run_matching(df, index, log)
        if stage == "match":
            export_results(df, config, log)
            return 0

    # ── Stage 5: Campus Refinement ────────────────────────────────────────
    if (run_all or stage == "refine") and not config.skip_refine:
        df = run_refinement(df, config, log)
        if stage == "refine":
            export_results(df, config, log)
            return 0

    # ── Stage 6: Export ───────────────────────────────────────────────────
    if run_all or stage == "export":
        paths = export_results(df, config, log)
        elapsed = time.time() - t0
        log.success(f"Pipeline complete in {elapsed:.1f}s")
        log.info(f"Outputs: {paths['csv']}")
        return 0

    return 0


def main() -> int:
    args = parse_args()

    from src.config import OUTPUT_DIR
    config = PipelineConfig(
        city=args.city,
        schools_csv=args.schools.resolve(),
        output_dir=(args.output or OUTPUT_DIR).resolve(),
        provider=args.provider,
        skip_download=args.skip_download,
        skip_geocode=args.skip_geocode,
        skip_match=args.skip_match,
        skip_refine=args.skip_refine,
    )

    print("\n" + "=" * 72)
    print("  K12 UNIFIED SPATIAL PIPELINE")
    print("=" * 72 + "\n", flush=True)

    return run_pipeline(config, stage=args.stage)


if __name__ == "__main__":
    sys.exit(main())
