"""Download Overture Maps feature layers for a city bounding box."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from src.city_extent import CityExtent
from src.config import PipelineConfig
from src.progress import ProgressLogger


def _overture_cli_available() -> bool:
    return shutil.which("overturemaps") is not None


def download_layer(
    extent: CityExtent,
    layer_type: str,
    output_path: Path,
    log: ProgressLogger,
) -> bool:
    """Download a single Overture layer via the overturemaps CLI."""
    if output_path.exists() and output_path.stat().st_size > 0:
        log.info(f"Skipping download — {output_path.name} already exists")
        return True

    if not _overture_cli_available():
        log.error(
            "overturemaps CLI not found. Install with: pip install overturemaps"
        )
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "overturemaps", "download",
        f"--bbox={extent.bbox_str}",
        "-f", "geojson",
        f"--type={layer_type}",
        "-o", str(output_path),
    ]
    log.info(f"Running: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        if result.returncode != 0:
            log.error(f"Overture download failed ({layer_type}): {result.stderr[:500]}")
            return False
        size_mb = output_path.stat().st_size / (1024 * 1024)
        log.success(f"Downloaded {layer_type} → {output_path.name} ({size_mb:.1f} MB)")
        return True
    except subprocess.TimeoutExpired:
        log.error(f"Overture download timed out for {layer_type}")
        return False
    except Exception as exc:
        log.error(f"Overture download error: {exc}")
        return False


def download_overture_data(
    config: PipelineConfig,
    extent: CityExtent,
    log: ProgressLogger | None = None,
) -> bool:
    """Download building and land_use Overture layers for the city extent."""
    log = log or ProgressLogger("Overture")
    log.stage("Overture Download", extent.bbox_str)

    ok_buildings = download_layer(extent, "building", config.buildings_path, log)
    ok_land_use = download_layer(extent, "land_use", config.land_use_path, log)

    if not ok_buildings:
        log.warn("Building layer download failed or skipped")
    if not ok_land_use:
        log.warn("Land use layer download failed or skipped — refinement may be limited")

    return ok_buildings
