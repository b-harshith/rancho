"""Footprint matching — assign schools to nearest Overture building polygons."""

from __future__ import annotations

import json
import math
import time
from collections import defaultdict
from pathlib import Path

import pandas as pd

from src.config import GRID_CELL_SIZE, MAX_MATCH_DIST_M, PipelineConfig
from src.progress import ProgressLogger


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def calculate_perimeter(coords: list) -> float:
    if not coords or len(coords) < 3:
        return 0.0
    total = 0.0
    for i in range(len(coords)):
        lat1, lon1 = coords[i]
        lat2, lon2 = coords[(i + 1) % len(coords)]
        total += haversine(lat1, lon1, lat2, lon2)
    return round(total, 2)


def centroid(coords: list) -> tuple[float, float]:
    lats = [c[0] for c in coords]
    lons = [c[1] for c in coords]
    return sum(lats) / len(lats), sum(lons) / len(lons)


class BuildingIndex:
    """Spatial grid index for fast nearest-building lookups."""

    def __init__(self, cell_size: float = GRID_CELL_SIZE):
        self.cs = cell_size
        self.cells: dict[tuple[int, int], list] = defaultdict(list)
        self.buildings: list[tuple] = []

    def _key(self, lat: float, lon: float) -> tuple[int, int]:
        return int(lat / self.cs), int(lon / self.cs)

    def insert(self, c_lat: float, c_lon: float, ring: list, perim: float):
        item = (c_lat, c_lon, ring, perim)
        self.buildings.append(item)
        self.cells[self._key(c_lat, c_lon)].append(item)

    def find_nearest(
        self, school_lat: float, school_lon: float, max_dist_m: float = MAX_MATCH_DIST_M
    ) -> tuple[list | None, float | None]:
        cx, cy = self._key(school_lat, school_lon)
        best_dist = float("inf")
        best_ring = None
        best_perim = None

        for dx in range(-1, 2):
            for dy in range(-1, 2):
                for c_lat, c_lon, ring, perim in self.cells.get((cx + dx, cy + dy), []):
                    if abs(c_lat - school_lat) > 0.005 or abs(c_lon - school_lon) > 0.005:
                        continue
                    dist = haversine(school_lat, school_lon, c_lat, c_lon)
                    if dist < best_dist:
                        best_dist = dist
                        best_ring = ring
                        best_perim = perim

        if best_dist <= max_dist_m:
            return best_ring, best_perim
        return None, None


def load_buildings(path: Path, log: ProgressLogger | None = None) -> BuildingIndex:
    """Load Overture building GeoJSON into a spatial index."""
    log = log or ProgressLogger("Footprint")
    log.info(f"Loading buildings from {path.name}...")
    t0 = time.time()
    index = BuildingIndex()
    count = 0

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('{"type": "FeatureCollection"') or line == "]}":
                continue
            if line.endswith(","):
                line = line[:-1]
            try:
                feat = json.loads(line)
                geom = feat.get("geometry", {})
                gtype = geom.get("type")
                coords_raw = geom.get("coordinates", [])

                if gtype == "Polygon" and coords_raw:
                    ring = [[c[1], c[0]] for c in coords_raw[0]]
                elif gtype == "MultiPolygon" and coords_raw:
                    best_ring = max(
                        (coords_raw[pi][0] for pi in range(len(coords_raw))),
                        key=lambda r: len(r),
                    )
                    ring = [[c[1], c[0]] for c in best_ring]
                else:
                    continue

                c_lat, c_lon = centroid(ring)
                perim = calculate_perimeter(ring)
                index.insert(c_lat, c_lon, ring, perim)
                count += 1
            except Exception:
                continue

    elapsed = time.time() - t0
    log.success(f"Indexed {count:,} building polygons in {elapsed:.1f}s")
    return index


def run_matching(
    df: pd.DataFrame,
    index: BuildingIndex,
    log: ProgressLogger | None = None,
) -> pd.DataFrame:
    """Match geocoded schools to nearest building footprints."""
    log = log or ProgressLogger("Footprint")

    if "Boundary_Polygon" not in df.columns:
        df["Boundary_Polygon"] = None
    if "Perimeter_Meters" not in df.columns:
        df["Perimeter_Meters"] = None

    valid = df[df["Latitude"].notna() & df["Longitude"].notna()]
    pending = valid["Boundary_Polygon"].isna().sum()
    log.stage("Footprint Matching", f"{pending} schools to match")

    stats = {"found": 0, "not_found": 0}

    for idx, row in df.iterrows():
        lat, lon = row.get("Latitude"), row.get("Longitude")
        if pd.isna(lat) or pd.isna(lon) or pd.notna(row.get("Boundary_Polygon")):
            continue

        code = str(row.get("School_Code", idx))
        name = str(row.get("Name", ""))
        ring, perim = index.find_nearest(float(lat), float(lon))

        if ring:
            df.at[idx, "Boundary_Polygon"] = json.dumps(ring)
            df.at[idx, "Perimeter_Meters"] = perim
            stats["found"] += 1
            log.event(code, name, "FOUND", f"{len(ring)} pts | {perim:.1f}m")
        else:
            stats["not_found"] += 1
            log.event(code, name, "MISSING", "No building within 200m")

    log.success(
        f"Matching complete: {stats['found']} found, {stats['not_found']} not found"
    )
    return df
