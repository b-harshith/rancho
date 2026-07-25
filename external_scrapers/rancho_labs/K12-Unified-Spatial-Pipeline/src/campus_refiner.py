"""Stage 2 — Campus polygon refinement via adjacent feature scoring."""

from __future__ import annotations

import json
from collections import defaultdict

import pandas as pd
from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.ops import unary_union
from shapely.validation import make_valid

from src.config import (
    GAP_TOLERANCE_DEG,
    GRID_CELL_SIZE,
    MERGE_THRESHOLD,
    SEARCH_BUFFER_DEG,
    PipelineConfig,
)
from src.footprint import haversine
from src.progress import ProgressLogger


class SpatialGrid:
    def __init__(self, cell_size: float = GRID_CELL_SIZE):
        self.cs = cell_size
        self.cells: dict[tuple[int, int], list] = defaultdict(list)

    def _key(self, lat: float, lon: float) -> tuple[int, int]:
        return int(lat / self.cs), int(lon / self.cs)

    def insert(self, lat: float, lon: float, item):
        self.cells[self._key(lat, lon)].append(item)

    def query(self, lat: float, lon: float, radius: int = 1) -> list:
        cx, cy = self._key(lat, lon)
        out = []
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                out.extend(self.cells.get((cx + dx, cy + dy), []))
        return out


def polygon_perimeter_m(shapely_poly) -> float:
    coords = list(shapely_poly.exterior.coords)
    total = 0.0
    for i in range(len(coords) - 1):
        x1, y1 = coords[i]
        x2, y2 = coords[i + 1]
        total += haversine(y1, x1, y2, x2)
    return round(total, 2)


def polygon_area_approx_sqm(shapely_poly) -> float:
    return abs(shapely_poly.area) * 111_000 * 108_000


_STOP_WORDS = {"of", "the", "and", "in", "at", "for", "a", "an", "pvt", "ltd", "-", "&"}
_EDU_KEYWORDS = {
    "school", "academy", "vidyalaya", "college", "institute", "education",
    "vidya", "shala", "montessori", "nursery", "kindergarten",
}


def extract_names(properties: dict) -> list[str]:
    names = []
    raw = properties.get("names")
    if isinstance(raw, dict):
        p = raw.get("primary")
        if isinstance(p, str):
            names.append(p.lower())
        common = raw.get("common")
        if isinstance(common, dict):
            for v in common.values():
                if isinstance(v, str):
                    names.append(v.lower())
    elif isinstance(raw, str):
        names.append(raw.lower())
    direct = properties.get("name")
    if isinstance(direct, str):
        names.append(direct.lower())
    return names


def fuzzy_name_match(school_name: str, feature_names: list[str]) -> int:
    if not feature_names:
        return 0
    s_words = set(school_name.lower().split()) - _STOP_WORDS
    best = 0
    for fn in feature_names:
        f_words = set(fn.split()) - _STOP_WORDS
        if not s_words or not f_words:
            continue
        overlap = s_words & f_words
        score = len(overlap) / max(len(s_words), len(f_words)) * 100
        best = max(best, score)
        if any(kw in fn for kw in _EDU_KEYWORDS):
            best = max(best, 20)
    return best


def score_candidate(
    school_poly, school_name: str, cand_poly, layer_type: str, properties: dict
) -> tuple[int, dict, float]:
    bd = {"proximity": 0, "feature_type": 0, "size_ratio": 0, "name_match": 0}
    dist_m = 0.0

    try:
        if cand_poly.intersects(school_poly):
            bd["proximity"] = 50 if cand_poly.touches(school_poly) else 60
        else:
            dist_m = school_poly.distance(cand_poly) * 111_000
            if dist_m <= 15:
                bd["proximity"] = 35
            elif dist_m <= 30:
                bd["proximity"] = 20
            elif dist_m <= 50:
                bd["proximity"] = 10
    except Exception:
        pass

    subtype = str(properties.get("subtype", "")).lower()
    fclass = str(properties.get("class", "")).lower()
    combined = subtype + " " + fclass
    is_water = any(k in combined for k in ("water", "wetland", "lake", "pond", "hazard", "tank"))

    if layer_type == "building":
        bd["feature_type"] = 20
    elif is_water or layer_type == "water":
        area = polygon_area_approx_sqm(cand_poly)
        bd["feature_type"] = 10 if area < 2000 else -20
    elif any(k in combined for k in ("education", "school", "institutional")):
        bd["feature_type"] = 40
    elif any(k in combined for k in ("recreation", "park", "playground", "sport", "garden", "grass")):
        bd["feature_type"] = 25
    elif any(k in combined for k in ("residential", "commercial", "industrial", "retail")):
        bd["feature_type"] = -15
    else:
        bd["feature_type"] = 5

    try:
        sa, ca = school_poly.area, cand_poly.area
        if sa > 0:
            r = ca / sa
            if r < 0.5:
                bd["size_ratio"] = 15
            elif r <= 2:
                bd["size_ratio"] = 10
            elif r <= 5:
                bd["size_ratio"] = 0
            elif r <= 10:
                bd["size_ratio"] = -25
            else:
                bd["size_ratio"] = -50
    except Exception:
        pass

    ns = fuzzy_name_match(school_name, extract_names(properties))
    if ns >= 70:
        bd["name_match"] = 40
    elif ns >= 40:
        bd["name_match"] = 20
    elif ns >= 20:
        bd["name_match"] = 10

    return sum(bd.values()), bd, dist_m


def _load_schools(df: pd.DataFrame) -> list[dict]:
    schools = []
    for idx, row in df.iterrows():
        ps = row.get("Boundary_Polygon")
        if not isinstance(ps, str) or len(ps) < 10:
            continue
        if pd.isna(row.get("Latitude")) or pd.isna(row.get("Longitude")):
            continue
        try:
            ring = json.loads(ps)
            shapely_ring = [(lon, lat) for lat, lon in ring]
            poly = Polygon(shapely_ring)
            if not poly.is_valid:
                poly = make_valid(poly)
            if poly.is_empty:
                continue
            c = poly.centroid
            schools.append({
                "idx": idx,
                "code": str(row.get("School_Code", idx)),
                "name": str(row.get("Name", "")),
                "lat": float(row["Latitude"]),
                "lon": float(row["Longitude"]),
                "poly": poly,
                "original_ring": ring,
                "original_perimeter": float(row.get("Perimeter_Meters", 0) or 0),
                "candidates": [],
                "c_lat": c.y,
                "c_lon": c.x,
            })
        except Exception:
            continue
    return schools


def _stream_overture_polygons(file_path: Path):
    if not file_path.exists() or file_path.stat().st_size == 0:
        return
    with open(file_path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith('{"type": "FeatureCollection"') or line == "]}":
                continue
            if line.endswith(","):
                line = line[:-1]
            try:
                feat = json.loads(line)
                geom = feat.get("geometry", {})
                gt = geom.get("type")
                props = feat.get("properties", {})

                if gt == "Polygon":
                    poly = shape(geom)
                elif gt == "MultiPolygon":
                    mp = shape(geom)
                    poly = max(mp.geoms, key=lambda p: p.area) if isinstance(mp, MultiPolygon) else mp
                else:
                    continue

                if not poly.is_valid:
                    poly = make_valid(poly)
                if poly.is_empty or poly.area == 0:
                    continue

                c = poly.centroid
                yield poly, c.y, c.x, props
            except Exception:
                continue


def run_refinement(
    df: pd.DataFrame,
    config: PipelineConfig,
    log: ProgressLogger | None = None,
) -> pd.DataFrame:
    """Refine campus boundaries by merging adjacent qualifying Overture features."""
    log = log or ProgressLogger("Refinement")
    log.stage("Campus Refinement", f"threshold ≥ {MERGE_THRESHOLD}")

    schools = _load_schools(df)
    if not schools:
        log.warn("No schools with boundary polygons to refine")
        return df

    log.info(f"Loaded {len(schools)} school polygons")

    grid = SpatialGrid(GRID_CELL_SIZE)
    for s in schools:
        grid.insert(s["c_lat"], s["c_lon"], s)
        minx, miny, maxx, maxy = s["poly"].bounds
        for lat in (miny, maxy):
            for lon in (minx, maxx):
                grid.insert(lat, lon, s)

    overture_layers = [
        (config.buildings_path, "building"),
        (config.land_use_path, "land_use"),
    ]

    stats = {"candidates": 0, "merged": 0, "rejected": 0, "features_scanned": 0}

    for fp, layer_type in overture_layers:
        if not fp.exists() or fp.stat().st_size == 0:
            log.warn(f"Skipping missing layer: {fp.name}")
            continue
        log.info(f"Scanning {fp.name} ({layer_type})...")
        feat_n = 0
        for poly, c_lat, c_lon, props in _stream_overture_polygons(fp):
            feat_n += 1
            stats["features_scanned"] += 1
            if feat_n % 100_000 == 0:
                log.info(f"  {layer_type}: {feat_n:,} features scanned...")

            nearby = grid.query(c_lat, c_lon, radius=1)
            if not nearby:
                continue

            seen_codes = set()
            for school in nearby:
                code = school["code"]
                if code in seen_codes:
                    continue
                seen_codes.add(code)

                buf = school["poly"].buffer(SEARCH_BUFFER_DEG)
                if not buf.intersects(poly):
                    continue
                if school["poly"].equals(poly) or school["poly"].equals_exact(poly, 1e-6):
                    continue

                score, bd, _ = score_candidate(
                    school["poly"], school["name"], poly, layer_type, props
                )
                stats["candidates"] += 1
                if score >= MERGE_THRESHOLD:
                    stats["merged"] += 1
                    school["candidates"].append({
                        "poly": poly, "layer_type": layer_type,
                        "score": score, "breakdown": bd,
                    })
                else:
                    stats["rejected"] += 1

    refined = 0
    area_deltas = []
    for school in schools:
        if not school["candidates"]:
            continue
        try:
            all_polys = [school["poly"]] + [c["poly"] for c in school["candidates"]]
            merged = unary_union(all_polys)
            merged = merged.buffer(GAP_TOLERANCE_DEG).buffer(-GAP_TOLERANCE_DEG)
            if not merged.is_valid:
                merged = make_valid(merged)
            if isinstance(merged, MultiPolygon):
                merged = max(merged.geoms, key=lambda p: p.area)
            if merged.is_empty:
                continue

            old_area = school["poly"].area
            new_area = merged.area
            pct = ((new_area - old_area) / old_area * 100) if old_area > 0 else 0
            area_deltas.append(pct)

            new_perim = polygon_perimeter_m(merged)
            old_perim = school["original_perimeter"]
            refined_ring = [[y, x] for x, y in merged.exterior.coords]

            ix = school["idx"]
            df.at[ix, "Boundary_Polygon"] = json.dumps(refined_ring)
            df.at[ix, "Perimeter_Meters"] = new_perim
            for col, val in [
                ("Refined_Stage2", True),
                ("Candidates_Merged", len(school["candidates"])),
                ("Area_Increase_Pct", round(pct, 1)),
                ("Original_Perimeter", old_perim),
            ]:
                if col not in df.columns:
                    df[col] = None
                if col == "Original_Perimeter" and pd.notna(df.at[ix, col]):
                    continue
                df.at[ix, col] = val

            refined += 1
            log.event(
                school["code"], school["name"], "REFINED",
                f"Merged {len(school['candidates'])} | +{pct:.1f}% area",
            )
        except Exception as exc:
            log.event(school["code"], school["name"], "ERROR", str(exc)[:60])

    avg_pct = round(sum(area_deltas) / len(area_deltas), 1) if area_deltas else 0
    log.success(
        f"Refinement complete: {refined} schools refined, "
        f"{stats['merged']} candidates merged, avg area +{avg_pct}%"
    )
    return df
