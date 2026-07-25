"""Pipeline configuration and path resolution."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
OVERTURE_DIR = DATA_DIR / "overture"
OUTPUT_DIR = PROJECT_ROOT / "output"
LOGS_DIR = PROJECT_ROOT / "logs"

GEOCODE_CACHE_DB = CACHE_DIR / "geocode_cache.db"

# Footprint matching
MAX_MATCH_DIST_M = 200
GRID_CELL_SIZE = 0.00100  # ~111 m

# Campus refinement
MERGE_THRESHOLD = 35
SEARCH_BUFFER_DEG = 0.00050  # ~55 m
GAP_TOLERANCE_DEG = 0.00001  # ~1.1 m


@dataclass
class PipelineConfig:
    city: str
    schools_csv: Path
    output_dir: Path = field(default_factory=lambda: OUTPUT_DIR)
    provider: str | None = None  # "google", "arcgis", "osm", or None for auto
    skip_download: bool = False
    skip_geocode: bool = False
    skip_match: bool = False
    skip_refine: bool = False

    def __post_init__(self):
        self.city_slug = self.city.strip().lower().replace(" ", "_")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        OVERTURE_DIR.mkdir(parents=True, exist_ok=True)
        LOGS_DIR.mkdir(parents=True, exist_ok=True)

    @property
    def buildings_path(self) -> Path:
        return OVERTURE_DIR / f"{self.city_slug}_buildings.geojson"

    @property
    def land_use_path(self) -> Path:
        return OVERTURE_DIR / f"{self.city_slug}_no_buildings.geojson"

    @property
    def master_csv_path(self) -> Path:
        return self.output_dir / f"{self.city_slug}_master.csv"

    @property
    def master_json_path(self) -> Path:
        return self.output_dir / f"{self.city_slug}_master.json"

    @property
    def master_geojson_path(self) -> Path:
        return self.output_dir / f"{self.city_slug}_master.geojson"

    @property
    def google_api_key(self) -> str | None:
        return os.environ.get("GOOGLE_MAPS_API_KEY")

    def default_provider(self) -> str:
        if self.provider:
            return self.provider
        return "google" if self.google_api_key else "arcgis"
