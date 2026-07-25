#!/usr/bin/env python3
"""
Geocoding Tool for K12 Bangalore Schools
Supports Google Maps (fast) with fallback to OpenStreetMap Nominatim.
Includes SQLite caching, incremental CSV saving, and live terminal dashboard.
"""

import os
import sys
import time
import sqlite3
import urllib.parse
import urllib.request
import json
import pandas as pd
import ssl
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Bypass SSL certificate verification issues (common on macOS Python installs)
ssl._create_default_https_context = ssl._create_unverified_context

# Load env variables from .env
load_dotenv()
GOOGLE_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")

if GOOGLE_API_KEY:
    PROVIDER = "Google Maps"
    DELAY = 0.05  # 20 req/sec — well within Google Maps limits
else:
    PROVIDER = "ArcGIS"
    DELAY = 0.1   # ArcGIS is very fast and has extremely high limits

# ── Paths ──────────────────────────────────────────────────────────────────────
PROJECT_ROOT   = Path(__file__).resolve().parent.parent
CSV_PATH       = Path("/Users/malleswararao/Desktop/Rancho Labs/BLR-SCHOOL-LIST/unique_schools_details.csv")
CACHE_DB_PATH  = PROJECT_ROOT / "data" / "cache" / "geocode_cache.db"

IS_TTY = sys.stdout.isatty()

# Only import rich when running interactively
if IS_TTY:
    from rich.console import Console
    from rich.live import Live
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
    from rich.align import Align
    from rich import box
    console = Console()


# ── SQLite Cache ───────────────────────────────────────────────────────────────
class GeocodeCache:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS geocode_cache (
                query TEXT PRIMARY KEY,
                latitude REAL,
                longitude REAL,
                success INTEGER,
                timestamp TEXT
            )
        """)
        self.conn.commit()

    def get(self, query: str):
        q = query.strip().lower()
        row = self.conn.execute(
            "SELECT latitude, longitude, success FROM geocode_cache WHERE query=?", (q,)
        ).fetchone()
        if row:
            lat, lon, ok = row
            return (lat, lon, True) if ok else (None, None, True)
        return None, None, False

    def set(self, query: str, lat, lon, success: bool):
        q = query.strip().lower()
        try:
            self.conn.execute("""
                INSERT OR REPLACE INTO geocode_cache (query, latitude, longitude, success, timestamp)
                VALUES (?,?,?,?,?)
            """, (q, lat, lon, 1 if success else 0, datetime.now().isoformat()))
            self.conn.commit()
        except Exception:
            pass

    def close(self):
        self.conn.close()


# ── Geocoding Functions ────────────────────────────────────────────────────────
def log_api_response(provider: str, query: str, response: dict):
    try:
        log_dir = PROJECT_ROOT / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "api_responses.log"
        with open(log_file, "a", encoding="utf-8") as f:
            ts = datetime.now().isoformat()
            entry = {
                "timestamp": ts,
                "provider": provider,
                "query": query,
                "response": response
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def query_google(query: str) -> tuple:
    url = "https://maps.googleapis.com/maps/api/geocode/json?" + urllib.parse.urlencode({
        "address": query, "key": GOOGLE_API_KEY
    })
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode())
    log_api_response("Google Maps", query, data)
    status = data.get("status")
    if status == "OK" and data.get("results"):
        loc = data["results"][0]["geometry"]["location"]
        return float(loc["lat"]), float(loc["lng"])
    if status == "OVER_QUERY_LIMIT":
        raise Exception("OVER_QUERY_LIMIT")
    return None, None


def query_osm(query: str) -> tuple:
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({
        "q": query, "format": "json", "limit": 1
    })
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Bangalore-K12-School-Geocoding-Agent/1.0")
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode())
    log_api_response("OpenStreetMap", query, data)
    if data:
        return float(data[0]["lat"]), float(data[0]["lon"])
    return None, None


def query_arcgis(query: str) -> tuple:
    try:
        url = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?" + urllib.parse.urlencode({
            "f": "json",
            "singleLine": query,
            "maxLocations": 1
        })
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
        log_api_response("ArcGIS", query, data)
        candidates = data.get("candidates")
        if candidates:
            loc = candidates[0]["location"]
            return float(loc["y"]), float(loc["x"])
    except Exception:
        pass
    return None, None


def geocode(query: str) -> tuple:
    """Query the active provider."""
    if GOOGLE_API_KEY:
        return query_google(query)
    # Use ArcGIS as primary, fallback to OpenStreetMap
    lat, lon = query_arcgis(query)
    if lat is not None:
        return lat, lon
    return query_osm(query)


# ── Dashboard (TTY only) ───────────────────────────────────────────────────────
def make_dashboard(stats, events, progress_bar, current):
    grid = Table.grid(expand=True)
    prov_color = "bright_green" if PROVIDER == "Google Maps" else "orange3"
    grid.add_row(Align.center(
        f"[bold cyan]🏫 K12 BANGALORE SCHOOL GEOCODER[/bold cyan] "
        f"[[bold {prov_color}]{PROVIDER}[/bold {prov_color}]]\n"
    ))

    stats_t = Table(box=box.ROUNDED, border_style="bright_blue", expand=True)
    for col in ["Metric", "Value", "Metric ", "Value "]:
        stats_t.add_column(col, ratio=1)

    p, t = stats["processed"], stats["total"]
    s, f = stats["success"], stats["fail"]
    c, a = stats["cache_hit"], stats["api_query"]
    sr = f"{s/p*100:.1f}%" if p > 0 else "—"
    cr = f"{c/p*100:.1f}%" if p > 0 else "—"

    stats_t.add_row("Total Schools",    str(t),            "Success Rate",  sr)
    stats_t.add_row("Processed",        f"{p} / {t}",      "Cache Hits",    f"{c} ({cr})")
    stats_t.add_row("Remaining",        str(t - p),        "API Queries",   str(a))
    stats_t.add_row("Coords Found",     f"[green]{s}[/green]", "Failures",  f"[red]{f}[/red]")
    grid.add_row(stats_t)

    disp = current or "[dim]Idle...[/dim]"
    grid.add_row(Panel(
        f"[bold yellow]Current:[/bold yellow] {disp}",
        border_style="yellow", title="[yellow]Active Query[/yellow]", title_align="left"
    ))
    grid.add_row("")

    log_t = Table(title="[bold magenta]Live Activity Log[/bold magenta]",
                  box=box.ROUNDED, border_style="magenta", expand=True)
    log_t.add_column("Time",    style="dim",    width=10)
    log_t.add_column("Code",    style="cyan",   width=16)
    log_t.add_column("Name",    style="white",  ratio=2)
    log_t.add_column("Type",    width=14)
    log_t.add_column("Status",  width=10)
    log_t.add_column("Details", style="green",  ratio=2)

    for ev in events[-10:]:
        st = ev["status"]
        sc = {"SUCCESS": "[bold green]SUCCESS[/bold green]",
              "CACHED":  "[bold blue]CACHED[/bold blue]",
              "FAIL":    "[bold red]FAIL[/bold red]",
              "SKIPPED": "[dim]SKIPPED[/dim]"}.get(st, st)
        tp = f"[yellow]{ev['type']}[/yellow]" if "API" in ev["type"] else f"[magenta]{ev['type']}[/magenta]"
        name = ev["name"][:34] + ("…" if len(ev["name"]) > 34 else "")
        log_t.add_row(ev["time"], ev["code"], name, tp, sc, ev["details"])

    grid.add_row(log_t)
    grid.add_row("")
    grid.add_row(Panel(progress_bar, border_style="cyan",
                       title="[cyan]Overall Progress[/cyan]", title_align="left"))
    return grid


def run_geocoding(df, cache, callback=None, stop_event=None, provider_override=None):
    global PROVIDER, DELAY
    if provider_override == "Google Maps" and GOOGLE_API_KEY:
        PROVIDER = "Google Maps"
        DELAY = 0.05
    elif provider_override == "ArcGIS":
        PROVIDER = "ArcGIS"
        DELAY = 0.1
    elif provider_override == "OpenStreetMap":
        PROVIDER = "OpenStreetMap"
        DELAY = 1.0

    total = len(df)
    already = int(df["Latitude"].notna().sum())

    stats  = {"total": total, "processed": already, "success": already,
              "fail": 0, "cache_hit": 0, "api_query": 0}
    events = []

    def log(code, name, typ, status, details):
        ts = datetime.now().strftime("%H:%M:%S")
        event = {"time": ts, "code": code, "name": name,
                 "type": typ, "status": status, "details": details}
        events.append(event)
        if len(events) > 60:
            events.pop(0)
        if callback:
            callback(stats, event, f"[{code}] {name}")

    def try_geocode(query, label, school_code, school_name):
        lat, lon, in_cache = cache.get(query)
        if in_cache:
            stats["cache_hit"] += 1
            if lat is not None:
                log(school_code, school_name, "CACHE_HIT", "CACHED", f"({lat:.5f}, {lon:.5f}) [{label}]")
                return lat, lon
            return None, None

        if stop_event and stop_event.is_set():
            return None, None

        time.sleep(DELAY)
        stats["api_query"] += 1
        try:
            lat, lon = geocode(query)
            if lat is not None:
                cache.set(query, lat, lon, True)
                log(school_code, school_name, f"{PROVIDER}_API", "SUCCESS", f"({lat:.5f}, {lon:.5f}) [{label}]")
                return lat, lon
            else:
                cache.set(query, 0, 0, False)
                log(school_code, school_name, f"{PROVIDER}_API", "FAIL", f"No results [{label}]")
        except Exception as e:
            log(school_code, school_name, "API_ERROR", "FAIL", str(e)[:60])
            time.sleep(2.0)
        return None, None

    last_save = time.time()
    current_school = ""

    for idx, row in df.iterrows():
        if stop_event and stop_event.is_set():
            log("SYS", "Pipeline", "STOP", "SKIPPED", "Processing paused by user.")
            break

        # Skip already-geocoded rows
        if pd.notna(row.get("Latitude")) and pd.notna(row.get("Longitude")):
            continue

        code = str(row["School_Code"])
        name = str(row["Name"])
        current_school = f"[{code}] {name}"

        gq   = str(row.get("Geocode_Query", "") or "")
        pin  = str(row.get("Pincode", "")       or "")
        if not gq or gq == "nan":
            gq = f"{name} {pin} Bangalore".strip()

        lat, lon = try_geocode(gq, "primary", code, name)
        if lat is None and not (stop_event and stop_event.is_set()):
            fallback_q = f"{name}, {pin}, Bangalore" if pin and pin != "nan" else f"{name}, Bangalore"
            lat, lon = try_geocode(fallback_q, "fallback", code, name)

        if lat is not None:
            df.at[idx, "Latitude"]  = lat
            df.at[idx, "Longitude"] = lon
            stats["success"] += 1
        else:
            if not (stop_event and stop_event.is_set()):
                df.at[idx, "Latitude"]  = None
                df.at[idx, "Longitude"] = None
                stats["fail"] += 1

        stats["processed"] += 1

        if callback and not (stop_event and stop_event.is_set()):
            callback(stats, None, current_school)

        # Incremental save every 10 or 30 sec
        if stats["processed"] % 10 == 0 or (time.time() - last_save) > 30:
            df.to_csv(CSV_PATH, index=False)
            last_save = time.time()
            log("SYS", "CSV Backup", "IO_SAVE", "SUCCESS",
                f"Saved at {stats['processed']}/{total}")

    df.to_csv(CSV_PATH, index=False)
    return stats


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    if not CSV_PATH.exists():
        print(f"ERROR: CSV not found at {CSV_PATH}", flush=True)
        sys.exit(1)

    print(f"[INIT] Provider: {PROVIDER}", flush=True)
    print(f"[INIT] Loading CSV: {CSV_PATH}", flush=True)

    cache = GeocodeCache(CACHE_DB_PATH)
    df = pd.read_csv(CSV_PATH)

    if "Latitude"  not in df.columns: df["Latitude"]  = None
    if "Longitude" not in df.columns: df["Longitude"] = None

    total = len(df)
    already = int(df["Latitude"].notna().sum())
    print(f"[INIT] Total: {total} | Already geocoded: {already} | To process: {total - already}", flush=True)

    stats  = {"total": total, "processed": already, "success": already,
              "fail": 0, "cache_hit": 0, "api_query": 0}
    events = [{"time": datetime.now().strftime("%H:%M:%S"), "code": "SYS", "name": "Initialization",
                "type": "INIT", "status": "SKIPPED",
                "details": f"Skipped {already} already geocoded schools."}]

    if IS_TTY:
        progress_bar = Progress(
            TextColumn("[bold blue]{task.completed}/{task.total}[/bold blue]"),
            BarColumn(bar_width=40),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(), TextColumn("ETA:"), TimeRemainingColumn()
        )
        task_id = progress_bar.add_task("geo", total=total, completed=already)

        def dashboard_callback(current_stats, new_event, current_school):
            stats.update(current_stats)
            if new_event:
                events.append(new_event)
                if len(events) > 60:
                    events.pop(0)
            progress_bar.update(task_id, completed=stats["processed"])
            live.update(make_dashboard(stats, events, progress_bar, current_school))

        try:
            with Live(make_dashboard(stats, events, progress_bar, ""),
                      refresh_per_second=4, console=console) as live:
                run_geocoding(df, cache, callback=dashboard_callback)
        except KeyboardInterrupt:
            print("\n[INTERRUPT] Saving progress and exiting...", flush=True)
        finally:
            cache.close()
    else:
        def console_callback(current_stats, new_event, current_school):
            stats.update(current_stats)
            if new_event:
                ts = new_event["time"]
                st = new_event["status"]
                tp = new_event["type"]
                code = new_event["code"]
                name = new_event["name"]
                details = new_event["details"]
                print(f"[{ts}] [{st:7s}] [{tp:15s}] {code} | {name[:40]} | {details}", flush=True)

        try:
            run_geocoding(df, cache, callback=console_callback)
        except KeyboardInterrupt:
            print("\n[INTERRUPT] Saving progress and exiting...", flush=True)
        finally:
            cache.close()


if __name__ == "__main__":
    main()
