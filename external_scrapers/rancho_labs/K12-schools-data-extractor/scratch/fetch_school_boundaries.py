#!/usr/bin/env python3
"""
School 2D Boundary Perimeter Extractor — Overture Maps Edition
Loads locally-downloaded Overture Maps building footprints for Bangalore,
spatially matches each geocoded school to its nearest building polygon,
and stores the boundary and perimeter in the CSV.
"""

import os
import sys
import json
import math
import time
import pandas as pd
from pathlib import Path
from datetime import datetime

# ── Paths ──────────────────────────────────────────────────────────────────────
PROJECT_ROOT   = Path(__file__).resolve().parent.parent
CSV_PATH       = Path("/Users/malleswararao/Desktop/Rancho Labs/BLR-SCHOOL-LIST/unique_schools_details.csv")
BUILDINGS_PATH = PROJECT_ROOT / "data" / "overture" / "bangalore_buildings.geojson"

IS_TTY = sys.stdout.isatty()

if IS_TTY:
    from rich.console import Console
    from rich.live import Live
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
    from rich.align import Align
    from rich import box
    console = Console()


# ── Haversine distance (meters) ───────────────────────────────────────────────
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def calculate_perimeter(coords):
    """Total perimeter of a polygon ring in meters."""
    if not coords or len(coords) < 3:
        return 0.0
    total = 0.0
    for i in range(len(coords)):
        lat1, lon1 = coords[i]
        lat2, lon2 = coords[(i + 1) % len(coords)]
        total += haversine(lat1, lon1, lat2, lon2)
    return round(total, 2)


def centroid(coords):
    """Simple centroid of a list of [lat, lon] pairs."""
    lats = [c[0] for c in coords]
    lons = [c[1] for c in coords]
    return sum(lats) / len(lats), sum(lons) / len(lons)


# ── Load Overture Buildings ───────────────────────────────────────────────────
def load_buildings(path: Path):
    """
    Loads the Overture GeoJSON line-by-line to save memory and handles large files.
    Returns a list of:
        (centroid_lat, centroid_lon, boundary_coords, perimeter_meters)
    """
    print(f"[LOAD] Reading Overture buildings from {path} line-by-line...", flush=True)
    t0 = time.time()

    buildings = []
    count = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith('{"type": "FeatureCollection"') or line == "]}" or not line:
                continue
            if line.endswith(","):
                line = line[:-1]
            
            try:
                feat = json.loads(line)
                count += 1
                geom = feat.get("geometry", {})
                gtype = geom.get("type")
                coords_raw = geom.get("coordinates", [])

                if gtype == "Polygon" and coords_raw:
                    # Outer ring: GeoJSON is [lon, lat]
                    ring = [[c[1], c[0]] for c in coords_raw[0]]
                    c_lat, c_lon = centroid(ring)
                    perim = calculate_perimeter(ring)
                    buildings.append((c_lat, c_lon, ring, perim))

                elif gtype == "MultiPolygon" and coords_raw:
                    # Take the largest ring (most vertices)
                    best_ring = max(
                        (coords_raw[pi][0] for pi in range(len(coords_raw))),
                        key=lambda r: len(r)
                    )
                    ring = [[c[1], c[0]] for c in best_ring]
                    c_lat, c_lon = centroid(ring)
                    perim = calculate_perimeter(ring)
                    buildings.append((c_lat, c_lon, ring, perim))
            except Exception:
                continue

    elapsed = time.time() - t0
    print(f"[LOAD] Read {count:,} features. Indexed {len(buildings):,} polygons in {elapsed:.1f}s", flush=True)
    return buildings


# ── Spatial Match ─────────────────────────────────────────────────────────────
def find_nearest_building(school_lat, school_lon, buildings, max_dist_m=200):
    """
    Finds the building whose centroid is closest to the school coords,
    within max_dist_m meters. Returns (ring, perimeter_meters) or (None, None).
    """
    best_dist = float("inf")
    best_ring = None
    best_perim = None

    for (c_lat, c_lon, ring, perim) in buildings:
        # Quick pre-filter: lat/lon box ±0.005 deg ≈ 550m — skip distant candidates fast
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


# ── Dashboard ─────────────────────────────────────────────────────────────────
def make_dashboard(stats, events, progress_bar, current):
    grid = Table.grid(expand=True)
    grid.add_row(Align.center(
        "[bold magenta]🗺️  OVERTURE MAPS — K12 SCHOOL BUILDING FOOTPRINT EXTRACTOR[/bold magenta]\n"
    ))

    stats_t = Table(box=box.ROUNDED, border_style="magenta", expand=True)
    for col in ["Metric", "Value", "Metric ", "Value "]:
        stats_t.add_column(col, ratio=1)

    p, t = stats["processed"], stats["total"]
    s, f = stats["found"], stats["not_found"]
    sr = f"{s/p*100:.1f}%" if p > 0 else "—"
    avg_perim = f"{stats['total_perim']/s:.0f}m" if s > 0 else "—"

    stats_t.add_row("Total Geocoded Schools", str(t),          "Match Rate",        sr)
    stats_t.add_row("Processed",             f"{p} / {t}",    "Avg Perimeter",     avg_perim)
    stats_t.add_row("Remaining",             str(t - p),      "Footprints Found",  f"[green]{s}[/green]")
    stats_t.add_row("Overture Buildings",    f"{stats['building_count']:,}", "Not Found", f"[red]{f}[/red]")
    grid.add_row(stats_t)

    disp = current or "[dim]Idle...[/dim]"
    grid.add_row(Panel(
        f"[bold yellow]Current:[/bold yellow] {disp}",
        border_style="yellow", title="[yellow]Active Match[/yellow]", title_align="left"
    ))
    grid.add_row("")

    log_t = Table(title="[bold cyan]Live Footprint Activity Log[/bold cyan]",
                  box=box.ROUNDED, border_style="cyan", expand=True)
    log_t.add_column("Time",       style="dim",   width=10)
    log_t.add_column("Code",       style="cyan",  width=16)
    log_t.add_column("Name",       style="white", ratio=2)
    log_t.add_column("Status",     width=12)
    log_t.add_column("Details",    style="green", ratio=2)

    for ev in events[-8:]:
        st = ev["status"]
        sc = {
            "FOUND":   "[bold green]FOUND 2D[/bold green]",
            "MISSING": "[bold red]NO MATCH[/bold red]",
            "SKIP":    "[dim]SKIPPED[/dim]",
        }.get(st, st)
        name = ev["name"][:36] + ("…" if len(ev["name"]) > 36 else "")
        log_t.add_row(ev["time"], ev["code"], name, sc, ev["details"])

    grid.add_row(log_t)
    grid.add_row("")
    grid.add_row(Panel(progress_bar, border_style="magenta",
                       title="[magenta]Progress[/magenta]", title_align="left"))
    return grid


def run_matching(df, buildings, callback=None, stop_event=None):
    valid = df[df["Latitude"].notna() & df["Longitude"].notna()]
    total = len(valid)
    already = int(df["Boundary_Polygon"].notna().sum())

    stats = {
        "total": total,
        "processed": already,
        "found": already,
        "not_found": 0,
        "total_perim": 0.0,
        "building_count": len(buildings),
    }
    events = []

    def log(code, name, status, details):
        ts = datetime.now().strftime("%H:%M:%S")
        event = {"time": ts, "code": code, "name": name, "status": status, "details": details}
        events.append(event)
        if len(events) > 50:
            events.pop(0)
        if callback:
            callback(stats, event, f"[{code}] {name}")

    last_save = time.time()
    current_school = ""

    for idx, row in df.iterrows():
        if stop_event and stop_event.is_set():
            log("SYS", "Pipeline", "STOP", "Processing paused by user.")
            break

        lat = row.get("Latitude")
        lon = row.get("Longitude")
        if pd.isna(lat) or pd.isna(lon):
            continue
        if pd.notna(row.get("Boundary_Polygon")):
            continue

        code = str(row["School_Code"])
        name = str(row["Name"])
        current_school = f"[{code}] {name}"

        flat, flon = float(lat), float(lon)
        ring, perim = find_nearest_building(flat, flon, buildings)

        if ring:
            df.at[idx, "Boundary_Polygon"] = json.dumps(ring)
            df.at[idx, "Perimeter_Meters"]  = perim
            stats["found"] += 1
            stats["total_perim"] += perim
            log(code, name, "FOUND", f"{len(ring)} pts | {perim:.1f}m perimeter")
        else:
            stats["not_found"] += 1
            log(code, name, "MISSING", "No building within 200m in Overture data")

        stats["processed"] += 1

        if callback and not (stop_event and stop_event.is_set()):
            callback(stats, None, current_school)

        if stats["processed"] % 10 == 0 or (time.time() - last_save) > 20:
            df.to_csv(CSV_PATH, index=False)
            last_save = time.time()
            log("SYS", "CSV Backup", "SKIP",
                f"Saved at {stats['processed']}/{total}")

    df.to_csv(CSV_PATH, index=False)
    return stats


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    # Validate inputs
    if not CSV_PATH.exists():
        print(f"ERROR: CSV not found at {CSV_PATH}", flush=True)
        sys.exit(1)
    if not BUILDINGS_PATH.exists():
        print(f"ERROR: Overture buildings file not found at {BUILDINGS_PATH}", flush=True)
        print("Please run the download first:", flush=True)
        print("  overturemaps download --bbox=77.35,12.70,77.85,13.25 -f geojson --type=building -o data/overture/bangalore_buildings.geojson", flush=True)
        sys.exit(1)

    # Load & index buildings
    buildings = load_buildings(BUILDINGS_PATH)

    # Load CSV
    print(f"[INIT] Loading CSV: {CSV_PATH}", flush=True)
    df = pd.read_csv(CSV_PATH)

    if "Latitude" not in df.columns or "Longitude" not in df.columns:
        print("ERROR: No Latitude/Longitude columns. Run geocode_schools.py first.", flush=True)
        sys.exit(1)

    if "Boundary_Polygon" not in df.columns:
        df["Boundary_Polygon"] = None
    if "Perimeter_Meters" not in df.columns:
        df["Perimeter_Meters"] = None

    valid = df[df["Latitude"].notna() & df["Longitude"].notna()]
    total = len(valid)
    already = int(df["Boundary_Polygon"].notna().sum())
    print(f"[INIT] Schools with coords: {total} | Already matched: {already} | To process: {total - already}", flush=True)

    stats = {
        "total": total,
        "processed": already,
        "found": already,
        "not_found": 0,
        "total_perim": 0.0,
        "building_count": len(buildings),
    }
    events = [{"time": datetime.now().strftime("%H:%M:%S"), "code": "SYS", "name": "Initialized",
               "status": "SKIP", "details": f"Skipped {already} already matched."}]

    if IS_TTY:
        progress_bar = Progress(
            TextColumn("[bold magenta]{task.completed}/{task.total}[/bold magenta]"),
            BarColumn(bar_width=40, style="grey35", complete_style="magenta"),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(), TextColumn("ETA:"), TimeRemainingColumn()
        )
        task_id = progress_bar.add_task("bounds", total=total, completed=already)

        def dashboard_callback(current_stats, new_event, current_school):
            stats.update(current_stats)
            if new_event:
                events.append(new_event)
                if len(events) > 50:
                    events.pop(0)
            progress_bar.update(task_id, completed=stats["processed"])
            live.update(make_dashboard(stats, events, progress_bar, current_school))

        try:
            with Live(make_dashboard(stats, events, progress_bar, ""),
                      refresh_per_second=4, console=console) as live:
                run_matching(df, buildings, callback=dashboard_callback)
        except KeyboardInterrupt:
            print("\n[INTERRUPT] Saving progress...", flush=True)
    else:
        def console_callback(current_stats, new_event, current_school):
            stats.update(current_stats)
            if new_event:
                ts = new_event["time"]
                st = new_event["status"]
                code = new_event["code"]
                name = new_event["name"]
                details = new_event["details"]
                print(f"[{ts}] [{st:7s}] {code} | {name[:40]} | {details}", flush=True)

        try:
            run_matching(df, buildings, callback=console_callback)
        except KeyboardInterrupt:
            print("\n[INTERRUPT] Saving progress...", flush=True)


if __name__ == "__main__":
    main()
