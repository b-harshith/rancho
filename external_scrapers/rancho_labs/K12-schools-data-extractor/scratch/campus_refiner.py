#!/usr/bin/env python3
"""
Stage 2 — Campus Polygon Refinement Engine
==========================================
Cross-verifies each school's building footprint against nearby Overture Maps
features (buildings, land_use, water bodies) and intelligently merges adjacent
polygons that likely belong to the school campus.

╔═══════════════════════════════════════════════════════════════════════════════╗
║                         SCORING RUBRIC                                      ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║ CRITERION                              SCORE    RATIONALE                   ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║ SPATIAL PROXIMITY                                                           ║
║   Overlaps / contains school polygon     +60    Same structure / shared space║
║   Touches (shares boundary edge)         +50    Adjacent wing or annex       ║
║   Within 15m gap                         +35    Very close, likely campus    ║
║   Within 30m gap                         +20    Probably campus annex        ║
║   Within 50m gap                         +10    Nearby, needs other signals  ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║ FEATURE TYPE                                                                ║
║   Building (any)                         +20    School wings, canteen, labs  ║
║   Land_use: education subtype            +40    School grounds              ║
║   Land_use: recreation / park            +25    Playground, sports field     ║
║   Land_use: residential / commercial     -15    Neighbor property, not school║
║   Water: small (< 2000 sqm)             +10    Campus pond / fountain       ║
║   Water: large (> 2000 sqm)             -20    Lake / reservoir             ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║ SIZE RATIO (candidate area / school area)                                   ║
║   < 0.5x school area                    +15    Small annex, shed, guard room║
║   0.5x – 2x school area                 +10    Similar-scale building       ║
║   2x – 5x school area                     0    Could be, neutral            ║
║   > 5x school area                       -25    Suspiciously large           ║
║   > 10x school area                      -50    Certainly not campus         ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║ NAME MATCHING                                                               ║
║   Fuzzy word overlap ≥ 70% w/ school     +40    Strong name match           ║
║   Fuzzy word overlap ≥ 40%               +20    Partial match               ║
║   Contains education keywords            +10    school/academy/vidyalaya     ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║ MERGE THRESHOLD: ≥ 35 points                                                ║
╚═══════════════════════════════════════════════════════════════════════════════╝

Usage (CLI):
    python3 scratch/campus_refiner.py

Usage (Dashboard):
    python3 scratch/refine_dashboard.py
    # then open http://localhost:8081
"""

import os
import sys
import json
import math
import time
import pandas as pd
from pathlib import Path
from collections import defaultdict
from datetime import datetime

from shapely.geometry import shape, Polygon, MultiPolygon
from shapely.ops import unary_union
from shapely.validation import make_valid

# ── Configuration ─────────────────────────────────────────────────────────────
PROJECT_ROOT    = Path(__file__).resolve().parent.parent
CSV_PATH        = Path("/Users/malleswararao/Desktop/Rancho Labs/BLR-SCHOOL-LIST/unique_schools_details.csv")
OVERTURE_DIR    = PROJECT_ROOT / "data" / "overture"

OVERTURE_LAYERS = [
    ("bangalore_buildings.geojson",     "building"),
    ("bangalore_no_buildings.geojson",  "land_use"),
]

MERGE_THRESHOLD     = 35       # Minimum score to merge a candidate
SEARCH_BUFFER_DEG   = 0.00050  # ~55m search radius at Bangalore latitude
GAP_TOLERANCE_DEG   = 0.00001  # ~1.1m tolerance for closing micro-gaps
GRID_CELL_SIZE      = 0.00100  # ~111m grid cells for spatial index

IS_TTY = sys.stdout.isatty()


# ── Haversine Distance ────────────────────────────────────────────────────────
def haversine(lat1, lon1, lat2, lon2):
    """Distance between two lat/lon points in meters."""
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def polygon_perimeter_m(shapely_poly):
    """Calculate perimeter in meters from a Shapely polygon in (lon, lat) coords."""
    coords = list(shapely_poly.exterior.coords)
    total = 0.0
    for i in range(len(coords) - 1):
        x1, y1 = coords[i]      # lon, lat
        x2, y2 = coords[i + 1]
        total += haversine(y1, x1, y2, x2)
    return round(total, 2)


def polygon_area_approx_sqm(shapely_poly):
    """Approximate polygon area in sq meters. At ~13°N: 1° lat ≈ 111km, 1° lon ≈ 108km."""
    return abs(shapely_poly.area) * 111_000 * 108_000


# ── Spatial Grid Index ────────────────────────────────────────────────────────
class SpatialGrid:
    """Dict-based grid for O(1) spatial proximity lookups."""

    def __init__(self, cell_size=GRID_CELL_SIZE):
        self.cs = cell_size
        self.cells = defaultdict(list)

    def _key(self, lat, lon):
        return (int(lat / self.cs), int(lon / self.cs))

    def insert(self, lat, lon, item):
        self.cells[self._key(lat, lon)].append(item)

    def query(self, lat, lon, radius=1):
        cx, cy = self._key(lat, lon)
        out = []
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                out.extend(self.cells.get((cx + dx, cy + dy), []))
        return out


# ── Name Extraction & Matching ────────────────────────────────────────────────
def extract_names(properties):
    """Extract name strings from various Overture property formats."""
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


_STOP_WORDS = {"of", "the", "and", "in", "at", "for", "a", "an", "pvt", "ltd", "-", "&"}
_EDU_KEYWORDS = {"school", "academy", "vidyalaya", "college", "institute", "education",
                 "vidya", "shala", "montessori", "nursery", "kindergarten"}


def fuzzy_name_match(school_name, feature_names):
    """Simple word-overlap matching. Returns 0-100 score."""
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


# ── Candidate Scoring ─────────────────────────────────────────────────────────
def score_candidate(school_poly, school_name, cand_poly, layer_type, properties):
    """
    Scores a candidate polygon for campus merge eligibility.

    Returns
    -------
    total_score : int
    breakdown   : dict  {proximity, feature_type, size_ratio, name_match}
    dist_m      : float  distance in metres between polygons
    """
    bd = {"proximity": 0, "feature_type": 0, "size_ratio": 0, "name_match": 0}
    dist_m = 0.0

    # ── 1. Spatial Proximity ──────────────────────────────────────────────
    try:
        if cand_poly.intersects(school_poly):
            # overlaps / within / contains / touches
            if cand_poly.touches(school_poly):
                bd["proximity"] = 50
            else:
                bd["proximity"] = 60
        else:
            dist_deg = school_poly.distance(cand_poly)
            dist_m = dist_deg * 111_000      # rough conversion
            if dist_m <= 15:
                bd["proximity"] = 35
            elif dist_m <= 30:
                bd["proximity"] = 20
            elif dist_m <= 50:
                bd["proximity"] = 10
    except Exception:
        pass

    # ── 2. Feature Type ───────────────────────────────────────────────────
    subtype = str(properties.get("subtype", "")).lower()
    fclass = str(properties.get("class", "")).lower()
    combined = subtype + " " + fclass

    is_water = any(k in combined for k in ("water", "wetland", "lake", "pond", "hazard", "tank"))

    if layer_type == "building":
        bd["feature_type"] = 20
    elif is_water or layer_type == "water":
        area = polygon_area_approx_sqm(cand_poly)
        bd["feature_type"] = 10 if area < 2000 else -20
    else:
        if any(k in combined for k in ("education", "school", "institutional")):
            bd["feature_type"] = 40
        elif any(k in combined for k in ("recreation", "park", "playground", "sport", "garden", "grass")):
            bd["feature_type"] = 25
        elif any(k in combined for k in ("residential", "commercial", "industrial", "retail")):
            bd["feature_type"] = -15
        else:
            bd["feature_type"] = 5

    # ── 3. Size Ratio ─────────────────────────────────────────────────────
    try:
        sa = school_poly.area
        ca = cand_poly.area
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

    # ── 4. Name Matching ──────────────────────────────────────────────────
    fnames = extract_names(properties)
    ns = fuzzy_name_match(school_name, fnames)
    if ns >= 70:
        bd["name_match"] = 40
    elif ns >= 40:
        bd["name_match"] = 20
    elif ns >= 20:
        bd["name_match"] = 10

    return sum(bd.values()), bd, dist_m


# ── Load Schools ──────────────────────────────────────────────────────────────
def load_schools(csv_path=CSV_PATH):
    """Load schools that have an existing boundary polygon from CSV."""
    df = pd.read_csv(csv_path)
    schools = []

    for idx, row in df.iterrows():
        ps = row.get("Boundary_Polygon")
        if not isinstance(ps, str) or len(ps) < 10:
            continue
        if pd.isna(row.get("Latitude")) or pd.isna(row.get("Longitude")):
            continue
        try:
            ring = json.loads(ps)                                # [[lat,lon], ...]
            shapely_ring = [(lon, lat) for lat, lon in ring]     # Shapely → (x=lon, y=lat)
            poly = Polygon(shapely_ring)
            if not poly.is_valid:
                poly = make_valid(poly)
            if poly.is_empty:
                continue
            c = poly.centroid
            schools.append({
                "idx": idx,
                "code": str(row["School_Code"]),
                "name": str(row["Name"]),
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

    return df, schools


# ── Stream Overture Polygons ──────────────────────────────────────────────────
def stream_overture_polygons(file_path):
    """Yields (shapely_polygon, centroid_lat, centroid_lon, properties) line-by-line."""
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


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN REFINEMENT LOOP
# ══════════════════════════════════════════════════════════════════════════════
def run_refinement(callback=None, stop_event=None):
    """
    Stage 2 campus polygon refinement.

    Parameters
    ----------
    callback : callable(stats_dict, event_dict_or_None, current_label_str)
    stop_event : threading.Event

    Returns
    -------
    stats : dict
    """
    t0 = time.time()

    def elapsed():
        d = int(time.time() - t0)
        return f"{d // 60}m {d % 60}s" if d >= 60 else f"{d}s"

    def emit(stats, ev, label):
        if stats:
            stats["elapsed"] = elapsed()
        if callback:
            callback(stats, ev, label)

    # ── Phase 1: Load schools ─────────────────────────────────────────────
    emit({}, _ev("SYS", "INFO", "Loader", "Loading school polygons from CSV..."), "Loading schools...")
    df, schools = load_schools()
    total_schools = len(schools)

    if total_schools == 0:
        emit({}, _ev("SYS", "FAIL", "Error", "No schools with polygons found in CSV."), "Error")
        return {}

    emit({}, _ev("SYS", "INFO", "Loader", f"Loaded {total_schools} school polygons"), f"{total_schools} schools loaded")

    # ── Phase 2: Build spatial grid ───────────────────────────────────────
    grid = SpatialGrid(GRID_CELL_SIZE)
    for s in schools:
        # Insert school centroid + polygon bounding-box corners into grid
        grid.insert(s["c_lat"], s["c_lon"], s)
        minx, miny, maxx, maxy = s["poly"].bounds
        for lat in (miny, maxy):
            for lon in (minx, maxx):
                grid.insert(lat, lon, s)

    stats = {
        "phase": "SCANNING",
        "total_schools": total_schools,
        "schools_refined": 0,
        "schools_unchanged": 0,
        "schools_processed": 0,
        "total_candidates": 0,
        "total_merged": 0,
        "total_rejected": 0,
        "avg_area_increase": 0.0,
        "current_layer": "",
        "features_scanned": 0,
        "elapsed": "0s",
    }

    emit(stats, _ev("SYS", "INFO", "Grid", f"Spatial grid built for {total_schools} schools"), "Grid ready")

    # ── Phase 3: Scan each Overture layer ─────────────────────────────────
    seen_layers = set()
    for filename, layer_type in OVERTURE_LAYERS:
        if stop_event and stop_event.is_set():
            break
        if layer_type in seen_layers:
            continue
        fp = OVERTURE_DIR / filename
        if not fp.exists() or fp.stat().st_size == 0:
            continue
        seen_layers.add(layer_type)

        stats["current_layer"] = layer_type
        layer_cands = 0
        mb = fp.stat().st_size / (1024 * 1024)
        emit(stats, _ev("SYS", "INFO", f"Layer: {layer_type}", f"Scanning {filename} ({mb:.0f} MB)..."), f"Scanning {layer_type}...")

        feat_n = 0
        for poly, c_lat, c_lon, props in stream_overture_polygons(fp):
            if stop_event and stop_event.is_set():
                break
            feat_n += 1
            stats["features_scanned"] += 1

            if feat_n % 100_000 == 0:
                emit(stats, None, f"Scanning {layer_type}: {feat_n:,} features...")

            # Quick grid lookup
            nearby = grid.query(c_lat, c_lon, radius=1)
            if not nearby:
                continue

            seen_codes = set()
            for school in nearby:
                code = school["code"]
                if code in seen_codes:
                    continue
                seen_codes.add(code)

                # Fast bounding-box rejection
                buf = school["poly"].buffer(SEARCH_BUFFER_DEG)
                if not buf.intersects(poly):
                    continue

                # Skip if this IS the school's original polygon
                if school["poly"].equals(poly) or school["poly"].equals_exact(poly, 1e-6):
                    continue

                # Score
                score, bd, dist = score_candidate(school["poly"], school["name"], poly, layer_type, props)

                stats["total_candidates"] += 1
                layer_cands += 1
                merged = score >= MERGE_THRESHOLD

                if merged:
                    stats["total_merged"] += 1
                    school["candidates"].append({"poly": poly, "layer_type": layer_type,
                                                 "score": score, "breakdown": bd})
                else:
                    stats["total_rejected"] += 1

                ev = {
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "code": code,
                    "status": "MERGED" if merged else "REJECTED",
                    "name": school["name"],
                    "details": (f"Score {score} ({layer_type}) | "
                                f"Prox:{bd['proximity']} Type:{bd['feature_type']} "
                                f"Size:{bd['size_ratio']} Name:{bd['name_match']}"),
                    "score": score, "merged": merged, "layer_type": layer_type,
                    "breakdown": bd,
                }
                try:
                    ev["candidate_polygon"] = [[y, x] for x, y in poly.exterior.coords]
                    ev["school_polygon"]    = school["original_ring"]
                    ev["lat"] = school["lat"]
                    ev["lon"] = school["lon"]
                except Exception:
                    pass
                emit(stats, ev, f"[{code}] {school['name']}")

        emit(stats, _ev("SYS", "INFO", f"Layer: {layer_type}",
                         f"Done — scanned {feat_n:,} features, {layer_cands} candidates"),
             f"Layer {layer_type} complete")

    # ── Phase 4: Merge candidates ─────────────────────────────────────────
    stats["phase"] = "MERGING"
    emit(stats, _ev("SYS", "INFO", "Merge", "Merging qualifying polygons into school footprints..."), "Merging...")

    area_deltas = []
    for school in schools:
        if stop_event and stop_event.is_set():
            break
        stats["schools_processed"] += 1

        if not school["candidates"]:
            stats["schools_unchanged"] += 1
            continue

        try:
            all_polys = [school["poly"]] + [c["poly"] for c in school["candidates"]]
            merged = unary_union(all_polys)
            # close micro-gaps
            merged = merged.buffer(GAP_TOLERANCE_DEG).buffer(-GAP_TOLERANCE_DEG)
            if not merged.is_valid:
                merged = make_valid(merged)
            if isinstance(merged, MultiPolygon):
                merged = max(merged.geoms, key=lambda p: p.area)
            if merged.is_empty:
                stats["schools_unchanged"] += 1
                continue

            old_area = school["poly"].area
            new_area = merged.area
            pct = ((new_area - old_area) / old_area * 100) if old_area > 0 else 0
            area_deltas.append(pct)

            new_perim = polygon_perimeter_m(merged)
            old_perim = school["original_perimeter"]

            refined_ring = [[y, x] for x, y in merged.exterior.coords]

            # Update DataFrame
            ix = school["idx"]
            df.at[ix, "Boundary_Polygon"] = json.dumps(refined_ring)
            df.at[ix, "Perimeter_Meters"] = new_perim
            for col, val in [("Refined_Stage2", True),
                             ("Candidates_Merged", len(school["candidates"])),
                             ("Area_Increase_Pct", round(pct, 1)),
                             ("Original_Perimeter", old_perim)]:
                if col not in df.columns:
                    df[col] = None
                if col == "Original_Perimeter" and pd.notna(df.at[ix, col]):
                    continue   # keep original from first run
                df.at[ix, col] = val

            stats["schools_refined"] += 1

            ev = {
                "time": datetime.now().strftime("%H:%M:%S"),
                "code": school["code"],
                "status": "REFINED",
                "name": school["name"],
                "details": (f"Merged {len(school['candidates'])} polys | "
                            f"Perimeter: {old_perim:.0f}m → {new_perim:.0f}m | "
                            f"Area +{pct:.1f}%"),
                "refined_polygon":  refined_ring,
                "original_polygon": school["original_ring"],
                "lat": school["lat"], "lon": school["lon"],
                "old_perimeter": old_perim, "new_perimeter": new_perim,
                "area_increase_pct": round(pct, 1),
                "candidates_count": len(school["candidates"]),
            }
            emit(stats, ev, f"[{school['code']}] {school['name']}")

        except Exception as e:
            stats["schools_unchanged"] += 1
            emit(stats, _ev(school["code"], "ERROR", school["name"], str(e)),
                 f"Error: {school['name']}")

    # ── Phase 5: Save ─────────────────────────────────────────────────────
    stats["phase"] = "COMPLETE"
    stats["avg_area_increase"] = round(sum(area_deltas) / len(area_deltas), 1) if area_deltas else 0.0
    df.to_csv(CSV_PATH, index=False)

    emit(stats, _ev("SYS", "SUCCESS", "Complete",
                     f"Refined {stats['schools_refined']} schools. "
                     f"Merged {stats['total_merged']} polygons. "
                     f"Avg area +{stats['avg_area_increase']:.1f}%"),
         "Done!")
    return stats


def _ev(code, status, name, details):
    return {"time": datetime.now().strftime("%H:%M:%S"),
            "code": code, "status": status, "name": name, "details": details}


# ══════════════════════════════════════════════════════════════════════════════
#  CLI ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════
def main():
    print("\n" + "=" * 72)
    print("  🔬 STAGE 2 — CAMPUS POLYGON REFINEMENT ENGINE")
    print("=" * 72)
    print(f"  CSV:      {CSV_PATH}")
    print(f"  Overture: {OVERTURE_DIR}")
    print(f"  Threshold: ≥{MERGE_THRESHOLD} points to merge")
    print("=" * 72 + "\n", flush=True)

    def cli_callback(stats, ev, label):
        if ev:
            ts   = ev.get("time", "")
            st   = ev.get("status", "")
            code = ev.get("code", "")
            name = ev.get("name", "")
            det  = ev.get("details", "")
            tag  = {"MERGED": "✅", "REJECTED": "❌", "REFINED": "🏫",
                    "INFO": "ℹ️ ", "SUCCESS": "🎉", "FAIL": "💥", "ERROR": "⚠️"}.get(st, "  ")
            print(f"  {tag} [{ts}] [{st:8s}] {code:>10s} | {name[:40]:40s} | {det}", flush=True)
        elif stats and label:
            print(f"  ⏳ {label}  (scanned {stats.get('features_scanned', 0):,} feats)", flush=True)

    try:
        stats = run_refinement(callback=cli_callback)
    except KeyboardInterrupt:
        print("\n[INTERRUPT] Saving progress...")
        return

    print("\n" + "=" * 72)
    print("  📊 FINAL RESULTS")
    print("=" * 72)
    for k, v in stats.items():
        print(f"    {k:>25s}:  {v}")
    print("=" * 72 + "\n", flush=True)


if __name__ == "__main__":
    main()
